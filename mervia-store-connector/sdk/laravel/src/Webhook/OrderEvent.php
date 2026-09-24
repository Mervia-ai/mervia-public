<?php

namespace Mervia\StoreConnector\Webhook;

use DateTimeInterface;
use InvalidArgumentException;
use Mervia\StoreConnector\Support\Money;
use Mervia\StoreConnector\Support\Payload;

/**
 * Builds the order webhook payload (contract/schemas/order-event.schema.json). By arrangement
 * with Mervia only: by default Mervia reads orders from GET /orders (Http\Resources\OrderResource)
 * and no store sends webhooks. The order object is the same as GET /orders returns.
 *
 * Call with named arguments:
 *
 *   OrderEvent::paid(storeId: config('mervia.store_id'), id: $order->id, paidAt: $order->paid_at,
 *       currency: 'USD', total: $order->total, lineItems: [...],
 *       merviaAttribution: $order->mervia_attribution);
 *
 * No customer name, email, phone or address is ever sent: `extra` keys that look like one are
 * refused, and `customerKey` must already be a SHA-256 hex digest (see customerKey()).
 */
final class OrderEvent
{
    public const EVENTS = ['order.paid', 'order.refunded', 'order.cancelled'];

    private const LINE_ITEM_KEYS = ['product_id', 'variant_id', 'sku', 'quantity', 'price'];

    public static function paid(mixed ...$args): array
    {
        return self::make('order.paid', ...$args);
    }

    public static function refunded(mixed ...$args): array
    {
        return self::make('order.refunded', ...$args);
    }

    public static function cancelled(mixed ...$args): array
    {
        return self::make('order.cancelled', ...$args);
    }

    /** SHA-256 of the trimmed, lowercased email: the only form a customer may appear in. */
    public static function customerKey(string $email): string
    {
        return hash('sha256', strtolower(trim($email)));
    }

    /**
     * @param array<int, array{product_id: string|int, quantity: int, price: string|int|float, variant_id?: string|int|null, sku?: string}> $lineItems
     * @param array<string, mixed> $extra Additional non-personal order fields (unknown fields are ignored by Mervia).
     */
    public static function make(
        string $event,
        string|int $storeId,
        string|int $id,
        DateTimeInterface|string $paidAt,
        string $currency,
        string|int|float $total,
        array $lineItems,
        ?string $number = null,
        string|int|float|null $subtotal = null,
        string|int|float|null $discountTotal = null,
        string|int|float|null $shipping = null,
        string|int|float|null $tax = null,
        string|int|float|null $refundedTotal = null,
        ?string $merviaAttribution = null,
        ?string $customerKey = null,
        array $extra = [],
        ?string $eventId = null,
        ?string $status = null,
        DateTimeInterface|string|null $updatedAt = null,
    ): array {
        if (!in_array($event, self::EVENTS, true)) {
            throw new InvalidArgumentException('event must be one of ' . implode(', ', self::EVENTS));
        }
        $currency = strtoupper(trim($currency));
        if (!preg_match('/^[A-Z]{3}$/', $currency)) {
            throw new InvalidArgumentException('currency must be an ISO 4217 code, e.g. USD');
        }
        if ($lineItems === []) {
            throw new InvalidArgumentException('lineItems must contain at least one item');
        }
        if ($customerKey !== null && !preg_match('/^[a-f0-9]{64}$/', $customerKey)) {
            throw new InvalidArgumentException('customerKey must be a lowercase SHA-256 hex digest; use OrderEvent::customerKey($email)');
        }
        // status follows the event unless given; refunded_total is a running total: 0 while
        // paid, the full total when cancelled, and required (the new cumulative amount) on a refund.
        $status ??= substr($event, strlen('order.'));
        if (!in_array($status, ['paid', 'refunded', 'cancelled'], true)) {
            throw new InvalidArgumentException('status must be paid, refunded or cancelled');
        }
        if ($refundedTotal === null) {
            $refundedTotal = match ($status) {
                'paid' => 0,
                'cancelled' => $total,
                default => throw new InvalidArgumentException('refundedTotal (the new cumulative amount) is required on a refund'),
            };
        }

        $order = [
            'id' => Payload::id($id, 'id'),
            'number' => $number,
            'status' => $status,
            'paid_at' => Payload::timestamp($paidAt, 'paidAt'),
            'updated_at' => Payload::timestamp($updatedAt ?? date(DATE_ATOM), 'updatedAt'),
            'currency' => $currency,
            'subtotal' => self::money($subtotal, 'subtotal'),
            'discount_total' => self::money($discountTotal, 'discountTotal'),
            'shipping' => self::money($shipping, 'shipping'),
            'tax' => self::money($tax, 'tax'),
            'total' => Money::format($total, 'total'),
            'refunded_total' => Money::format($refundedTotal, 'refundedTotal'),
            'line_items' => array_map(self::lineItem(...), array_values($lineItems)),
            'mervia_attribution' => $merviaAttribution,
            'customer_key' => $customerKey,
        ];
        // Optional fields are omitted when absent; mervia_attribution is always sent (null = no cookie).
        $order = array_filter($order, fn ($v, $k) => $v !== null || $k === 'mervia_attribution', ARRAY_FILTER_USE_BOTH);

        Payload::assertNoPii($extra, 'extra');
        foreach ($extra as $key => $value) {
            if (array_key_exists($key, $order)) {
                throw new InvalidArgumentException("extra must not override the order field \"{$key}\"");
            }
            $order[$key] = $value;
        }

        return [
            'event_id' => $eventId ?? Payload::eventId(),
            'event' => $event,
            'store_id' => Payload::id($storeId, 'storeId'),
            'order' => $order,
        ];
    }

    private static function money(string|int|float|null $amount, string $field): ?string
    {
        return $amount === null ? null : Money::format($amount, $field);
    }

    private static function lineItem(array $item): array
    {
        foreach (['product_id', 'quantity', 'price'] as $required) {
            if (!array_key_exists($required, $item)) {
                throw new InvalidArgumentException("each line item needs {$required}");
            }
        }
        Payload::assertNoPii($item, 'line item');
        if (!is_int($item['quantity']) || $item['quantity'] < 1) {
            throw new InvalidArgumentException('line item quantity must be an integer of at least 1');
        }
        $out = [
            'product_id' => Payload::id($item['product_id'], 'line item product_id'),
            'quantity' => $item['quantity'],
            'price' => Money::format($item['price'], 'line item price'),
        ];
        if (array_key_exists('variant_id', $item)) {
            if (!is_string($item['variant_id']) && !is_int($item['variant_id']) && $item['variant_id'] !== null) {
                throw new InvalidArgumentException('line item variant_id must be a string, an integer or null');
            }
            $out['variant_id'] = $item['variant_id'];
        }
        if (isset($item['sku'])) {
            $out['sku'] = (string) $item['sku'];
        }
        // Any other non-personal field passes through unchanged.
        return $out + array_diff_key($item, array_flip(self::LINE_ITEM_KEYS));
    }
}
