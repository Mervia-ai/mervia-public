<?php

/**
 * Item 6, pull alternative (by arrangement with Mervia only; the default is push, see
 * MerviaProductContent): the product-page include, PHP 7.4, curl + a cache directory.
 *
 *   $mervia = new MerviaInclude(getenv('MERVIA_INCLUDE_URL'), getenv('MERVIA_INCLUDE_KEY'), '/var/cache/mervia');
 *   <head> ... <?php $mervia->printHead($product['id']); ?> </head>
 *   ... <?php $mervia->printBody($product['id']); ?> ...
 *
 * 1-second timeout, 15-minute cache per product, the last good copy on any error or timeout,
 * nothing at all (not even a warning) when there is none. 404 means nothing is live: print
 * nothing and drop the last good copy. The include key stays on the server.
 */
final class MerviaInclude
{
    private $baseUrl;
    private $key;
    private $cacheDir;
    private $timeoutMs;
    private $cacheSeconds;
    private $errorCacheSeconds;
    private $clock;
    private $memo = array();

    /**
     * @param array $options timeout_ms (1000), cache_seconds (900), error_cache_seconds (60),
     *                       clock (callable returning unix seconds; for tests)
     */
    public function __construct(?string $includeUrl, ?string $includeKey, string $cacheDir, array $options = array())
    {
        $this->baseUrl = rtrim((string) $includeUrl, '/');
        $this->key = (string) $includeKey;
        $this->cacheDir = rtrim($cacheDir, '/');
        $this->timeoutMs = isset($options['timeout_ms']) ? (int) $options['timeout_ms'] : 1000;
        $this->cacheSeconds = isset($options['cache_seconds']) ? (int) $options['cache_seconds'] : 900;
        $this->errorCacheSeconds = isset($options['error_cache_seconds']) ? (int) $options['error_cache_seconds'] : 60;
        $this->clock = isset($options['clock']) ? $options['clock'] : 'time';
    }

    public function printHead($productId): void
    {
        $doc = $this->fetch($productId);
        echo $doc['head_html'];
    }

    public function printBody($productId): void
    {
        $doc = $this->fetch($productId);
        echo $doc['body_html'];
    }

    /** @return array{head_html: string, body_html: string} Never throws. */
    public function fetch($productId): array
    {
        try {
            if ((!is_string($productId) && !is_int($productId)) || (string) $productId === '' || $this->baseUrl === '' || $this->key === '') {
                return self::doc(null);
            }
            $id = (string) $productId;
            // Head and body on one page share one lookup.
            if (!isset($this->memo[$id])) {
                $this->memo[$id] = $this->lookup($id);
            }
            return $this->memo[$id];
        } catch (Throwable $e) {
            return self::doc(null);
        }
    }

    private function lookup(string $id): array
    {
        $now = (int) call_user_func($this->clock);
        $file = $this->cacheDir . '/' . sha1($this->baseUrl . '|' . $id);
        $fresh = $this->read($file . '.json');
        if ($fresh !== null && isset($fresh['expires_at']) && $fresh['expires_at'] > $now) {
            return self::doc($fresh);
        }
        $lastGood = $this->read($file . '.last-good.json');

        $headers = array('Authorization: Bearer ' . $this->key, 'Accept: application/json');
        if ($lastGood !== null && !empty($lastGood['etag'])) {
            $headers[] = 'If-None-Match: ' . $lastGood['etag'];
        }
        $res = $this->get($this->baseUrl . '/products/' . rawurlencode($id), $headers);

        if ($res['status'] === 304 && $lastGood !== null) {
            $this->write($file . '.json', self::doc($lastGood) + array('expires_at' => $now + $this->cacheSeconds));
            return self::doc($lastGood);
        }
        if ($res['status'] === 404) {
            $this->write($file . '.json', self::doc(null) + array('expires_at' => $now + $this->cacheSeconds));
            @unlink($file . '.last-good.json');
            return self::doc(null);
        }
        $json = $res['status'] === 200 ? json_decode($res['body'], true) : null;
        if (is_array($json) && isset($json['head_html'], $json['body_html']) && is_string($json['head_html']) && is_string($json['body_html'])) {
            $doc = self::doc($json);
            $this->write($file . '.json', $doc + array('expires_at' => $now + $this->cacheSeconds));
            $this->write($file . '.last-good.json', $doc + array('etag' => $res['etag']));
            return $doc;
        }
        // Error, timeout or malformed answer: last good copy, retried after a short pause.
        $fallback = self::doc($lastGood);
        $this->write($file . '.json', $fallback + array('expires_at' => $now + $this->errorCacheSeconds));
        return $fallback;
    }

    /** @return array{status: int, body: string, etag: string} status 0 on a network error or timeout */
    private function get(string $url, array $headers): array
    {
        $etag = '';
        $ch = curl_init($url);
        curl_setopt_array($ch, array(
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_TIMEOUT_MS => $this->timeoutMs,
            CURLOPT_CONNECTTIMEOUT_MS => $this->timeoutMs,
            CURLOPT_NOSIGNAL => 1, // required for sub-second timeouts
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_HEADERFUNCTION => function ($ch, $line) use (&$etag) {
                if (stripos($line, 'etag:') === 0) {
                    $etag = trim(substr($line, 5));
                }
                return strlen($line);
            },
        ));
        $body = curl_exec($ch);
        $status = $body === false ? 0 : (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        return array('status' => $status, 'body' => (string) $body, 'etag' => $etag);
    }

    private function read(string $path): ?array
    {
        $raw = @file_get_contents($path);
        $data = $raw === false ? null : json_decode($raw, true);
        return is_array($data) ? $data : null;
    }

    private function write(string $path, array $data): void
    {
        if (!is_dir($this->cacheDir) && !@mkdir($this->cacheDir, 0775, true) && !is_dir($this->cacheDir)) {
            return;
        }
        $tmp = @tempnam($this->cacheDir, 'mervia');
        if ($tmp !== false && @file_put_contents($tmp, json_encode($data)) !== false) {
            @chmod($tmp, 0664);
            @rename($tmp, $path);
        } elseif ($tmp !== false) {
            @unlink($tmp);
        }
    }

    private static function doc(?array $d): array
    {
        return array(
            'head_html' => ($d !== null && isset($d['head_html']) && is_string($d['head_html'])) ? $d['head_html'] : '',
            'body_html' => ($d !== null && isset($d['body_html']) && is_string($d['body_html'])) ? $d['body_html'] : '',
        );
    }
}
