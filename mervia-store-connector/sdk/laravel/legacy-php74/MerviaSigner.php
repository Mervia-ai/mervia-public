<?php

/**
 * Webhook signing for the by-arrangement order and product webhooks, PHP 7.4, no dependencies (contract 1.0.0-draft.3).
 *
 * X-Mervia-Timestamp: <unix seconds at send time>
 * X-Mervia-Signature: sha256=<lowercase hex HMAC-SHA256, keyed with the secret, of "<timestamp>.<RAW body>">
 *
 * The HMAC input is the timestamp header's exact value, one ".", then the raw body, so a captured
 * delivery cannot be resent later with a fresh timestamp. Sign the exact bytes you send.
 */
final class MerviaSigner
{
    const TOLERANCE_SECONDS = 300;

    /** @return array{X-Mervia-Signature: string, X-Mervia-Timestamp: string} */
    public static function sign(string $rawBody, string $secret, int $timestamp): array
    {
        return array(
            'X-Mervia-Signature' => self::signature($rawBody, $secret, (string) $timestamp),
            'X-Mervia-Timestamp' => (string) $timestamp,
        );
    }

    /** The header value for a body and the exact X-Mervia-Timestamp value it is sent with. */
    public static function signature(string $rawBody, string $secret, string $timestamp): string
    {
        return 'sha256=' . hash_hmac('sha256', $timestamp . '.' . $rawBody, $secret);
    }

    /** Constant-time check against the body and the X-Mervia-Timestamp value it arrived with; the timestamp must be within 5 minutes of $now. */
    public static function verify(string $rawBody, string $secret, string $signatureHeader, string $timestampHeader, ?int $now = null): bool
    {
        if (!hash_equals(self::signature($rawBody, $secret, $timestampHeader), $signatureHeader)) {
            return false;
        }
        if (!ctype_digit($timestampHeader) || abs(($now === null ? time() : $now) - (int) $timestampHeader) > self::TOLERANCE_SECONDS) {
            return false;
        }
        return true;
    }
}
