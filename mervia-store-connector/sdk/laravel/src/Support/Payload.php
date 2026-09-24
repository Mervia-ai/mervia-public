<?php

namespace Mervia\StoreConnector\Support;

use DateTimeInterface;
use InvalidArgumentException;

/** Small validators shared by the webhook payload builders. */
final class Payload
{
    /** Key fragments that mark customer personal data. Webhooks never carry any. */
    public const PII_FRAGMENTS = ['email', 'name', 'phone', 'address'];

    public static function eventId(): string
    {
        $b = random_bytes(16);
        $b[6] = chr((ord($b[6]) & 0x0f) | 0x40);
        $b[8] = chr((ord($b[8]) & 0x3f) | 0x80);
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($b), 4));
    }

    public static function id(string|int $id, string $field): string|int
    {
        if (is_string($id) && trim($id) === '') {
            throw new InvalidArgumentException("{$field} must not be empty");
        }
        return $id;
    }

    public static function timestamp(DateTimeInterface|string $at, string $field): string
    {
        if ($at instanceof DateTimeInterface) {
            return $at->format(DATE_ATOM);
        }
        if (!preg_match('/^(\d{4})-(\d{2})-(\d{2})T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d+)?(Z|[+-]\d{2}:\d{2})$/', $at, $m)
            || !checkdate((int) $m[2], (int) $m[3], (int) $m[1])) {
            throw new InvalidArgumentException("{$field} must be ISO 8601 with a timezone, e.g. 2026-09-23T10:00:00-07:00");
        }
        return $at;
    }

    /** Refuse any key (at any depth) that looks like customer personal data, and email-shaped values. */
    public static function assertNoPii(array $data, string $where): void
    {
        foreach ($data as $key => $value) {
            $k = strtolower((string) $key);
            foreach (self::PII_FRAGMENTS as $fragment) {
                if (str_contains($k, $fragment)) {
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
}
