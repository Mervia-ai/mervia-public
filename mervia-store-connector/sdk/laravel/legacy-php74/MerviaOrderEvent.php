<?php

/**
 * The order object (contract/schemas/order.schema.json) and the by-arrangement webhook payloads,
 * PHP 7.4, no dependencies.
 *
 * MerviaOrderEvent::order($row) normalises one order for GET /orders (MerviaOrders) and refuses
 * customer personal data. The webhook builders below exist by arrangement with Mervia only: by
 * default Mervia reads GET /orders and no store sends webhooks.
 *
 * Order events (contract/schemas/order-event.schema.json), using the contract's own keys:
 *
 *   $payload = MerviaOrderEvent::build('order.paid', 'example-us', array(
 *       'id' => $order['id'], 'number' => '#1042', 'paid_at' => '2026-09-23T10:15:00-07:00',
 *       'currency' => 'USD', 'total' => '136.16', 'shipping' => '5.00',
 *       'line_items' => array(array('product_id' => 'p1', 'quantity' => 1, 'price' => '129.50')),
 *       'mervia_attribution' => $order['mervia_attribution'],   // raw cookie value or null
 *   ));
 *
 * Money: decimal strings, padded to at least two decimals ("129.5" becomes "129.50", "1.250" stays),
 * or int/float whole units (a float with more than two decimals is refused: pass a string).
 * No customer name, email, phone or address is ever sent: such keys are refused, and
 * customer_key must already be a SHA-256 digest (MerviaOrderEvent::customerKey($email)).
 * Unknown order keys are refused to catch typos; put other non-personal fields in $extra.
 */
final class MerviaOrderEvent
{
    const EVENTS = array('order.paid', 'order.refunded', 'order.cancelled');
    const PRODUCT_EVENTS = array('product.updated', 'product.deleted');
    const PII_FRAGMENTS = array('email', 'name', 'phone', 'address');
    const ORDER_KEYS = array('id', 'number', 'status', 'paid_at', 'updated_at', 'currency', 'subtotal', 'discount_total', 'shipping', 'tax', 'total', 'refunded_total', 'line_items', 'mervia_attribution', 'customer_key');
    const STATUSES = array('paid', 'refunded', 'cancelled');
    const MONEY_KEYS = array('subtotal', 'discount_total', 'shipping', 'tax', 'total', 'refunded_total');

    public static function build(string $event, $storeId, array $order, array $extra = array(), ?string $eventId = null): array
    {
        if (!in_array($event, self::EVENTS, true)) {
            throw new InvalidArgumentException('event must be one of ' . implode(', ', self::EVENTS));
        }
        self::assertNoPii($extra, 'extra');
        // status follows the event unless given; updated_at defaults to now; refunded_total is a
        // running total: 0 while paid, the full total when cancelled, required on a refund.
        $status = substr($event, strlen('order.'));
        $defaults = array('status' => $status, 'updated_at' => date(DATE_ATOM));
        if (!isset($order['refunded_total'])) {
            if ($status === 'refunded') {
                throw new InvalidArgumentException('order.refunded_total (the new cumulative amount) is required on a refund');
            }
            $defaults['refunded_total'] = $status === 'cancelled' ? (isset($order['total']) ? $order['total'] : null) : '0.00';
        }
        $out = self::order($order, $defaults);
        foreach ($extra as $key => $value) {
            if (array_key_exists($key, $out)) {
                throw new InvalidArgumentException("extra must not override the order field \"{$key}\"");
            }
            $out[$key] = $value;
        }
        return array(
            'event_id' => $eventId !== null ? $eventId : self::eventId(),
            'event' => $event,
            'store_id' => self::id($storeId, 'store_id'),
            'order' => $out,
        );
    }

    /**
     * One order as GET /orders lists it (contract/schemas/order.schema.json), normalised: ids kept,
     * money padded to two decimals, timestamps checked, personal data refused, unknown keys refused.
     *
     * @param array $order    the contract's keys (see ORDER_KEYS)
     * @param array $defaults values for status, updated_at and refunded_total when the row has none
     */
    public static function order(array $order, array $defaults = array()): array
    {
        self::assertNoPii($order, 'order');
        $unknown = array_diff(array_keys($order), self::ORDER_KEYS);
        if ($unknown) {
            throw new InvalidArgumentException('unknown order key(s): ' . implode(', ', $unknown));
        }
        foreach ($defaults as $key => $value) {
            if (!isset($order[$key]) && $value !== null) {
                $order[$key] = $value;
            }
        }
        foreach (array('id', 'status', 'paid_at', 'updated_at', 'currency', 'total', 'refunded_total', 'line_items') as $required) {
            if (!isset($order[$required])) {
                throw new InvalidArgumentException("order.{$required} is required");
            }
        }
        if (!in_array($order['status'], self::STATUSES, true)) {
            throw new InvalidArgumentException('order.status must be paid, refunded or cancelled (only paid orders are listed)');
        }
        $out = array('id' => self::id($order['id'], 'order.id'));
        if (isset($order['number'])) {
            $out['number'] = (string) $order['number'];
        }
        $out['status'] = $order['status'];
        $out['paid_at'] = self::timestamp($order['paid_at'], 'order.paid_at');
        $out['updated_at'] = self::timestamp($order['updated_at'], 'order.updated_at');
        $out['currency'] = strtoupper(trim((string) $order['currency']));
        if (!preg_match('/^[A-Z]{3}$/', $out['currency'])) {
            throw new InvalidArgumentException('order.currency must be an ISO 4217 code, e.g. USD');
        }
        foreach (self::MONEY_KEYS as $key) {
            if (isset($order[$key])) {
                $out[$key] = self::money($order[$key], "order.{$key}");
            }
        }
        if (!is_array($order['line_items']) || count($order['line_items']) === 0) {
            throw new InvalidArgumentException('order.line_items must contain at least one item');
        }
        $out['line_items'] = array_map(array(self::class, 'lineItem'), array_values($order['line_items']));
        $attribution = isset($order['mervia_attribution']) ? $order['mervia_attribution'] : null;
        $out['mervia_attribution'] = ($attribution === null || $attribution === '') ? null : (string) $attribution;
        if (isset($order['customer_key'])) {
            if (!is_string($order['customer_key']) || !preg_match('/^[a-f0-9]{64}$/', $order['customer_key'])) {
                throw new InvalidArgumentException('order.customer_key must be a lowercase SHA-256 hex digest; use MerviaOrderEvent::customerKey($email)');
            }
            $out['customer_key'] = $order['customer_key'];
        }
        return $out;
    }

    /** ISO 8601 with seconds and a timezone? */
    public static function isTimestamp($at): bool
    {
        return is_string($at) && preg_match('/^(\d{4})-(\d{2})-(\d{2})T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d+)?(Z|[+-]\d{2}:\d{2})$/', $at, $m)
            && checkdate((int) $m[2], (int) $m[3], (int) $m[1]);
    }

    /** Item 11 (by arrangement): product.updated / product.deleted (contract/schemas/product-event.schema.json). */
    public static function product(string $event, $storeId, $productId, ?string $updatedAt = null, ?string $eventId = null): array
    {
        if (!in_array($event, self::PRODUCT_EVENTS, true)) {
            throw new InvalidArgumentException('event must be one of ' . implode(', ', self::PRODUCT_EVENTS));
        }
        $out = array(
            'event_id' => $eventId !== null ? $eventId : self::eventId(),
            'event' => $event,
            'store_id' => self::id($storeId, 'store_id'),
            'product_id' => self::id($productId, 'product_id'),
        );
        if ($updatedAt !== null) {
            $out['updated_at'] = self::timestamp($updatedAt, 'updated_at');
        }
        return $out;
    }

    /** SHA-256 of the trimmed, lowercased email: the only form a customer may appear in. */
    public static function customerKey(string $email): string
    {
        return hash('sha256', strtolower(trim($email)));
    }

    public static function money($amount, string $field = 'amount'): string
    {
        if (is_int($amount)) {
            return $amount . '.00';
        }
        if (is_float($amount) && is_finite($amount) && abs(round($amount, 2) - $amount) <= 1e-9) {
            return number_format($amount, 2, '.', '');
        }
        if (is_string($amount) && preg_match('/^(-?)(\d+)(?:\.(\d+))?$/', trim($amount), $m)) {
            return $m[1] . $m[2] . '.' . str_pad(isset($m[3]) ? $m[3] : '', 2, '0');
        }
        throw new InvalidArgumentException("{$field} must be a decimal string such as \"129.00\" (a float may carry at most two decimals)");
    }

    private static function lineItem($item): array
    {
        if (!is_array($item)) {
            throw new InvalidArgumentException('each line item must be an array');
        }
        self::assertNoPii($item, 'line item');
        foreach (array('product_id', 'quantity', 'price') as $required) {
            if (!array_key_exists($required, $item)) {
                throw new InvalidArgumentException("each line item needs {$required}");
            }
        }
        if (!is_int($item['quantity']) || $item['quantity'] < 1) {
            throw new InvalidArgumentException('line item quantity must be an integer of at least 1');
        }
        $out = array(
            'product_id' => self::id($item['product_id'], 'line item product_id'),
            'quantity' => $item['quantity'],
            'price' => self::money($item['price'], 'line item price'),
        );
        if (array_key_exists('variant_id', $item)) {
            if (!is_string($item['variant_id']) && !is_int($item['variant_id']) && $item['variant_id'] !== null) {
                throw new InvalidArgumentException('line item variant_id must be a string, an integer or null');
            }
            $out['variant_id'] = $item['variant_id'];
        }
        if (isset($item['sku'])) {
            $out['sku'] = (string) $item['sku'];
        }
        return $out + array_diff_key($item, array_flip(array('product_id', 'variant_id', 'sku', 'quantity', 'price')));
    }

    private static function id($id, string $field)
    {
        if (is_int($id) || (is_string($id) && trim($id) !== '')) {
            return $id;
        }
        throw new InvalidArgumentException("{$field} must be a non-empty string or an integer");
    }

    private static function timestamp($at, string $field): string
    {
        if ($at instanceof DateTimeInterface) {
            return $at->format(DATE_ATOM);
        }
        if (self::isTimestamp($at)) {
            return $at;
        }
        throw new InvalidArgumentException("{$field} must be ISO 8601 with a timezone, e.g. 2026-09-23T10:00:00-07:00");
    }

    private static function assertNoPii(array $data, string $where): void
    {
        foreach ($data as $key => $value) {
            foreach (self::PII_FRAGMENTS as $fragment) {
                if (strpos(strtolower((string) $key), $fragment) !== false) {
                    throw new InvalidArgumentException("{$where} must not carry customer personal data (key \"{$key}\")");
                }
            }
            if (is_array($value)) {
                self::assertNoPii($value, $where);
            } elseif (is_string($value) && preg_match('/[^@\s]+@[^@\s]+\.[^@\s]+/', $value)) {
                throw new InvalidArgumentException("{$where} must not carry customer personal data (an email address under \"{$key}\")");
            }
        }
    }

    private static function eventId(): string
    {
        $b = random_bytes(16);
        $b[6] = chr((ord($b[6]) & 0x0f) | 0x40);
        $b[8] = chr((ord($b[8]) & 0x3f) | 0x80);
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($b), 4));
    }
}
