<?php

/**
 * The mervia_attr cookie set by Mervia's tracking tag (item 7), PHP 7.4.
 *
 * At checkout, save MerviaAttributionCookie::forOrder() on the order as it is (a nullable text
 * column) and send that stored value as mervia_attribution in the order webhook. Do not parse it.
 *
 * "Raw" means the bytes the browser sent, read from the Cookie header without URL-decoding
 * (PHP's $_COOKIE would turn "+" into a space and decode "%xx"); $_COOKIE is only the fallback.
 */
final class MerviaAttributionCookie
{
    const NAME = 'mervia_attr';

    /** @param array|null $cookies a cookie array to read instead of the request (for tests) */
    public static function raw(?array $cookies = null): ?string
    {
        if ($cookies === null) {
            $header = isset($_SERVER['HTTP_COOKIE']) ? (string) $_SERVER['HTTP_COOKIE'] : '';
            foreach (explode(';', $header) as $pair) {
                $parts = explode('=', trim($pair), 2);
                if ($parts[0] === self::NAME && isset($parts[1]) && $parts[1] !== '') {
                    return $parts[1];
                }
            }
            $cookies = $_COOKIE;
        }
        $value = isset($cookies[self::NAME]) ? $cookies[self::NAME] : null;
        return (is_string($value) && $value !== '') ? $value : null;
    }

    public static function forOrder(?array $cookies = null): ?string
    {
        return self::raw($cookies);
    }
}
