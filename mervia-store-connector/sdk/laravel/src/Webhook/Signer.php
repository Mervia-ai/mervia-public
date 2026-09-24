<?php

namespace Mervia\StoreConnector\Webhook;

/**
 * Webhook signing for the by-arrangement order and product webhooks (contract 1.0.0-draft.3).
 *
 * X-Mervia-Timestamp: <unix seconds at send time>
 * X-Mervia-Signature: sha256=<lowercase hex HMAC-SHA256, keyed with the secret, of "<timestamp>.<RAW request body>">
 *
 * The HMAC input is the timestamp header's exact value, one ".", then the raw body. Sign the
 * exact bytes you send: re-encoding the payload after signing breaks the signature. Because the
 * timestamp is signed, a captured delivery cannot be resent later with a fresh timestamp; Mervia
 * rejects a timestamp more than 300 s from its clock and also ignores a repeated event_id.
 */
final class Signer
{
    public const SIGNATURE_HEADER = 'X-Mervia-Signature';
    public const TIMESTAMP_HEADER = 'X-Mervia-Timestamp';
    public const TOLERANCE_SECONDS = 300;

    /** @return array{X-Mervia-Signature: string, X-Mervia-Timestamp: string} */
    public static function sign(string $rawBody, string $secret, int $timestamp): array
    {
        return [
            self::SIGNATURE_HEADER => self::signature($rawBody, $secret, (string) $timestamp),
            self::TIMESTAMP_HEADER => (string) $timestamp,
        ];
    }

    /** The header value for a body and the exact X-Mervia-Timestamp value it is sent with. */
    public static function signature(string $rawBody, string $secret, string $timestamp): string
    {
        return 'sha256=' . hash_hmac('sha256', $timestamp . '.' . $rawBody, $secret);
    }

    /**
     * Constant-time check of a signature header against the body and the X-Mervia-Timestamp
     * value it arrived with. The timestamp must also be within five minutes of $now (default:
     * the current time), as Mervia enforces.
     */
    public static function verify(
        string $rawBody,
        string $secret,
        string $signatureHeader,
        string $timestampHeader,
        ?int $now = null,
    ): bool {
        if (!hash_equals(self::signature($rawBody, $secret, $timestampHeader), $signatureHeader)) {
            return false;
        }
        if (!ctype_digit($timestampHeader) || abs(($now ?? time()) - (int) $timestampHeader) > self::TOLERANCE_SECONDS) {
            return false;
        }
        return true;
    }
}
