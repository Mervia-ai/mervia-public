<?php

namespace Mervia\StoreConnector\Webhook;

use DateTimeInterface;
use InvalidArgumentException;
use Mervia\StoreConnector\Support\Payload;

/** Builds the item 11 product-changed webhook payload (contract/schemas/product-event.schema.json). */
final class ProductEvent
{
    public const EVENTS = ['product.updated', 'product.deleted'];

    public static function updated(string|int $storeId, string|int $productId, DateTimeInterface|string|null $updatedAt = null, ?string $eventId = null): array
    {
        return self::make('product.updated', $storeId, $productId, $updatedAt, $eventId);
    }

    public static function deleted(string|int $storeId, string|int $productId, DateTimeInterface|string|null $updatedAt = null, ?string $eventId = null): array
    {
        return self::make('product.deleted', $storeId, $productId, $updatedAt, $eventId);
    }

    public static function make(
        string $event,
        string|int $storeId,
        string|int $productId,
        DateTimeInterface|string|null $updatedAt = null,
        ?string $eventId = null,
    ): array {
        if (!in_array($event, self::EVENTS, true)) {
            throw new InvalidArgumentException('event must be one of ' . implode(', ', self::EVENTS));
        }
        $payload = [
            'event_id' => $eventId ?? Payload::eventId(),
            'event' => $event,
            'store_id' => Payload::id($storeId, 'storeId'),
            'product_id' => Payload::id($productId, 'productId'),
        ];
        if ($updatedAt !== null) {
            $payload['updated_at'] = Payload::timestamp($updatedAt, 'updatedAt');
        }
        return $payload;
    }
}
