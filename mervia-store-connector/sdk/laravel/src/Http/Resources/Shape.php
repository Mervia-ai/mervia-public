<?php

namespace Mervia\StoreConnector\Http\Resources;

use DateTimeInterface;
use Mervia\StoreConnector\Support\Money;

/** Small helpers the resource stubs share. */
final class Shape
{
    /** ISO 8601 with timezone, or null. */
    public static function time(mixed $value): ?string
    {
        return $value instanceof DateTimeInterface ? $value->format(DATE_ATOM) : ($value ?: null);
    }

    /** A money string, or null when the column is null (the field is then left out). */
    public static function money(mixed $value): ?string
    {
        return $value === null ? null : Money::format($value);
    }

    /**
     * Drop null values: the contract types optional fields as non-nullable, so an absent value
     * is left out rather than sent as null. Keys in $nullable (the contract's nullable fields)
     * are kept even when null.
     */
    public static function compact(array $data, array $nullable = []): array
    {
        return array_filter($data, fn ($v, $k) => $v !== null || in_array($k, $nullable, true), ARRAY_FILTER_USE_BOTH);
    }
}
