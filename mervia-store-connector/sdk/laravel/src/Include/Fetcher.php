<?php

namespace Mervia\StoreConnector\Include;

use Illuminate\Contracts\Cache\Repository;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use Throwable;

/**
 * Item 6, pull alternative (by arrangement with Mervia only; the default is push, see
 * Content\ProductContent): fetches Mervia's product-page document on the server.
 *
 * Rules (contract/schemas/include-response.schema.json): 1-second timeout, 15-minute cache
 * per product, the last good copy on any error or timeout, nothing when there is none. A 404
 * means nothing is live for the product: empty strings, and the last good copy is dropped.
 * Never throws; the worst case is two empty strings.
 */
class Fetcher
{
    private const EMPTY = ['head_html' => '', 'body_html' => ''];

    /** @return array{head_html: string, body_html: string} */
    public function fetch(mixed $productId): array
    {
        try {
            if (!is_string($productId) && !is_int($productId)) {
                return self::EMPTY;
            }
            return $this->fetchOrFail((string) $productId);
        } catch (Throwable) {
            return self::EMPTY;
        }
    }

    private function fetchOrFail(string $productId): array
    {
        $base = rtrim((string) config('mervia.include_url'), '/');
        $key = (string) config('mervia.include_key');
        if ($base === '' || $key === '' || $productId === '') {
            return self::EMPTY;
        }

        $cache = $this->cache();
        $freshKey = 'mervia:include:' . sha1($base . '|' . $productId);
        $lastGoodKey = $freshKey . ':last-good';

        $fresh = $this->read($cache, $freshKey);
        if (is_array($fresh)) {
            return self::document($fresh);
        }

        $lastGood = $this->read($cache, $lastGoodKey);
        $lastGood = is_array($lastGood) ? $lastGood : null;
        $ttl = (int) config('mervia.include_cache_seconds', 900);

        try {
            // Guzzle options take fractional seconds on every Laravel version (10's timeout() is int-only).
            $timeout = max(0.1, (float) config('mervia.include_timeout_seconds', 1));
            $request = Http::withToken($key)
                ->acceptJson()
                ->withOptions(['timeout' => $timeout, 'connect_timeout' => $timeout]);
            if ($lastGood !== null && ($lastGood['etag'] ?? '') !== '') {
                $request = $request->withHeaders(['If-None-Match' => $lastGood['etag']]);
            }
            $response = $request->get($base . '/products/' . rawurlencode($productId));
            $status = $response->status();

            if ($status === 304 && $lastGood !== null) {
                $this->quietly(fn () => $cache->put($freshKey, $lastGood, $ttl));
                return self::document($lastGood);
            }
            if ($status === 404) {
                $this->quietly(fn () => $cache->put($freshKey, self::EMPTY, $ttl));
                $this->quietly(fn () => $cache->forget($lastGoodKey));
                return self::EMPTY;
            }
            $json = $status === 200 ? $response->json() : null;
            if (is_array($json) && is_string($json['head_html'] ?? null) && is_string($json['body_html'] ?? null)) {
                $doc = self::document($json) + ['etag' => (string) $response->header('ETag')];
                $this->quietly(fn () => $cache->put($freshKey, $doc, $ttl));
                $this->quietly(fn () => $cache->forever($lastGoodKey, $doc));
                return self::document($doc);
            }
        } catch (Throwable) {
            // Timeout or connection failure: fall through to the last good copy.
        }

        $fallback = $lastGood ?? self::EMPTY;
        $this->quietly(fn () => $cache->put($freshKey, $fallback, (int) config('mervia.include_error_cache_seconds', 60)));
        return self::document($fallback);
    }

    /** An unreachable cache reads as a miss: the page still gets a fetch. */
    private function read(Repository $cache, string $key): mixed
    {
        try {
            return $cache->get($key);
        } catch (Throwable) {
            return null;
        }
    }

    /** A cache that refuses a write must not cost the page a document already fetched. */
    private function quietly(callable $write): void
    {
        try {
            $write();
        } catch (Throwable) {
        }
    }

    private function cache(): Repository
    {
        return Cache::store(config('mervia.include_cache_store'));
    }

    private static function document(array $doc): array
    {
        return [
            'head_html' => is_string($doc['head_html'] ?? null) ? $doc['head_html'] : '',
            'body_html' => is_string($doc['body_html'] ?? null) ? $doc['body_html'] : '',
        ];
    }
}
