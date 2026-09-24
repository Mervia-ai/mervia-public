<?php

namespace Mervia\StoreConnector\Attribution;

use Illuminate\Http\Request;

/**
 * The mervia_attr cookie, set by Mervia's tracking tag (item 7) on a visit that came from an
 * AI assistant.
 *
 * At checkout, store Cookie::forOrder() on the order as it is (a nullable text column), and
 * send that stored value as `mervia_attribution` in the order webhook. Do not parse it, and
 * do not read it later from the webhook job: the job runs without the shopper's request.
 *
 * "Raw" means the bytes the browser sent, read from the Cookie header without URL-decoding
 * (PHP's cookie parsing would turn "+" into a space and decode "%xx"). Only when the header is
 * unavailable does it fall back to Laravel's cookie bag. The provider also exempts the cookie
 * from Laravel's EncryptCookies on Laravel 11+, since the tag sets it unencrypted in the browser.
 */
final class Cookie
{
    public const NAME = 'mervia_attr';

    public static function raw(?Request $request = null): ?string
    {
        $request ??= request();

        foreach (explode(';', (string) $request->headers->get('Cookie', '')) as $pair) {
            [$name, $value] = array_pad(explode('=', trim($pair), 2), 2, null);
            if ($name === self::NAME && $value !== null && $value !== '') {
                return $value;
            }
        }

        $value = $request->cookies->get(self::NAME);
        return is_string($value) && $value !== '' ? $value : null;
    }

    public static function forOrder(?Request $request = null): ?string
    {
        return self::raw($request);
    }
}
