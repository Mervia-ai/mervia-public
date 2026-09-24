<?php

namespace Mervia\StoreConnector\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/**
 * Route middleware `mervia.auth`: accepts `Authorization: Bearer <key>` matching the current
 * or the previous key (config mervia.api_key_for_mervia / _previous), so a key can be rotated
 * without downtime. Anything else is 401 {"error":"unauthorized"}. Constant-time compare.
 */
class AuthenticateMervia
{
    public function handle(Request $request, Closure $next): Response
    {
        $given = (string) $request->bearerToken();
        $accepted = array_filter([
            (string) config('mervia.api_key_for_mervia'),
            (string) config('mervia.api_key_for_mervia_previous'),
        ], fn (string $k) => $k !== '');

        $ok = false;
        foreach ($accepted as $key) {
            $ok = hash_equals($key, $given) || $ok;
        }
        if ($given === '' || !$ok) {
            return response()->json(['error' => 'unauthorized', 'message' => 'Missing or invalid API key'], 401);
        }
        return $next($request);
    }
}
