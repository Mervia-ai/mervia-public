<?php

/**
 * Sends the by-arrangement signed webhooks (order and product events), PHP 7.4, curl + a spool directory, no queue needed.
 *
 *   $sender = new MerviaWebhookSender(getenv('MERVIA_WEBHOOK_URL'), getenv('MERVIA_WEBHOOK_SECRET'), '/var/spool/mervia');
 *   $sender->send($payload);      // tries once now; on failure spools it for retry
 *   // or $sender->enqueue($payload) to keep the checkout request fast, and let cron send it.
 *
 *   # crontab: every minute
 *   * * * * * php /path/to/mervia-retry.php     # calls $sender->retryPending()
 *
 * Every attempt signs the raw body afresh with the current timestamp; event_id never changes,
 * so Mervia ignores a delivery it already accepted. 2xx is success. Retries back off from one
 * minute to eight hours and stop after 12 attempts or 24 hours; a given-up event is moved to
 * <spool>/failed/, as is an entry cron cannot read. Neither the secret nor the payload is ever logged.
 * Run cron as the web server's user, or in its group (spool files are 0660).
 */
final class MerviaWebhookSender
{
    const BACKOFF = array(60, 120, 300, 600, 1200, 1800, 3600, 7200, 14400, 21600, 28800);
    const MAX_ATTEMPTS = 12;
    const MAX_AGE_SECONDS = 86400;

    private $url;
    private $secret;
    private $spoolDir;
    private $timeoutSeconds;
    private $clock;

    /** @param array $options timeout_seconds (5), clock (callable returning unix seconds; for tests) */
    public function __construct(string $webhookUrl, string $secret, string $spoolDir, array $options = array())
    {
        if ($webhookUrl === '' || $secret === '') {
            throw new InvalidArgumentException('Mervia webhook URL and secret are required');
        }
        $this->url = $webhookUrl;
        $this->secret = $secret;
        $this->spoolDir = rtrim($spoolDir, '/');
        $this->timeoutSeconds = isset($options['timeout_seconds']) ? (int) $options['timeout_seconds'] : 5;
        $this->clock = isset($options['clock']) ? $options['clock'] : 'time';
    }

    /** Try now; on failure spool for retryPending(). Returns true when Mervia accepted it. */
    public function send(array $payload): bool
    {
        $body = self::encode($payload);
        if ($this->post($body)) {
            return true;
        }
        $now = $this->now();
        $this->spool((string) $payload['event_id'], array('body' => $body, 'attempts' => 1, 'first_attempt_at' => $now, 'next_attempt_at' => $now + self::BACKOFF[0]));
        return false;
    }

    /** Spool without trying; the next retryPending() sends it. */
    public function enqueue(array $payload): void
    {
        $now = $this->now();
        $body = self::encode($payload);
        $this->spool((string) $payload['event_id'], array('body' => $body, 'attempts' => 0, 'first_attempt_at' => $now, 'next_attempt_at' => $now));
    }

    /** Send every due spooled event. Safe to run from overlapping cron jobs. */
    public function retryPending(): array
    {
        $stats = array('sent' => 0, 'retrying' => 0, 'gave_up' => 0);
        if (!is_dir($this->spoolDir)) {
            return $stats;
        }
        $lock = @fopen($this->spoolDir . '/.lock', 'c');
        if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) {
            return $stats; // another run is busy
        }
        try {
            foreach (glob($this->spoolDir . '/*.json') ?: array() as $path) {
                $entry = json_decode((string) @file_get_contents($path), true);
                if (!is_array($entry) || !isset($entry['body'], $entry['attempts'], $entry['first_attempt_at'], $entry['next_attempt_at'])) {
                    // Unreadable (permissions) or corrupt: park it where a human will see it.
                    $this->giveUp($path, 'unreadable or corrupt spool entry');
                    $stats['gave_up']++;
                    continue;
                }
                $now = $this->now();
                if ($entry['next_attempt_at'] > $now) {
                    continue;
                }
                if ($this->post($entry['body'])) {
                    @unlink($path);
                    $stats['sent']++;
                    continue;
                }
                $entry['attempts']++;
                if ($entry['attempts'] >= self::MAX_ATTEMPTS || $now - $entry['first_attempt_at'] >= self::MAX_AGE_SECONDS) {
                    $this->giveUp($path, 'gave up after ' . $entry['attempts'] . ' attempts');
                    $stats['gave_up']++;
                    continue;
                }
                $entry['next_attempt_at'] = $now + self::BACKOFF[min($entry['attempts'], count(self::BACKOFF)) - 1];
                self::writeAtomic($path, json_encode($entry));
                $stats['retrying']++;
            }
        } finally {
            flock($lock, LOCK_UN);
            fclose($lock);
        }
        return $stats;
    }

    private function post(string $body): bool
    {
        $headers = array('Content-Type: application/json');
        foreach (MerviaSigner::sign($body, $this->secret, $this->now()) as $name => $value) {
            $headers[] = $name . ': ' . $value;
        }
        $ch = curl_init($this->url);
        curl_setopt_array($ch, array(
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $body,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => $this->timeoutSeconds,
            CURLOPT_CONNECTTIMEOUT => $this->timeoutSeconds,
            CURLOPT_FOLLOWLOCATION => false,
        ));
        $ok = curl_exec($ch) !== false;
        $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        return $ok && $status >= 200 && $status < 300;
    }

    private function giveUp(string $path, string $why): void
    {
        @mkdir($this->spoolDir . '/failed', 0775, true);
        @rename($path, $this->spoolDir . '/failed/' . basename($path));
        error_log('Mervia webhook ' . $why . ': ' . $this->spoolDir . '/failed/' . basename($path));
    }

    /** Spool files are named by a hash of the event_id: any event_id is safe, a repeat overwrites. */
    private function spool(string $eventId, array $entry): void
    {
        if (!is_dir($this->spoolDir) && !@mkdir($this->spoolDir, 0775, true) && !is_dir($this->spoolDir)) {
            error_log('Mervia webhook spool directory is not writable; event ' . $eventId . ' was not saved');
            return;
        }
        self::writeAtomic($this->spoolDir . '/' . sha1($eventId) . '.json', json_encode($entry));
    }

    private static function encode(array $payload): string
    {
        if (!isset($payload['event_id'], $payload['event']) || (string) $payload['event_id'] === '') {
            throw new InvalidArgumentException('payload needs event_id and event (build it with MerviaOrderEvent)');
        }
        // Invalid UTF-8 becomes U+FFFD rather than an event that can never be sent.
        $body = json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
        if ($body === false) {
            throw new InvalidArgumentException('payload cannot be encoded as JSON: ' . json_last_error_msg());
        }
        return $body;
    }

    private static function writeAtomic(string $path, string $contents): void
    {
        $tmp = @tempnam(dirname($path), 'mervia');
        if ($tmp !== false && @file_put_contents($tmp, $contents) !== false) {
            @chmod($tmp, 0660); // tempnam makes 0600; cron may run as another user in the web server's group
            @rename($tmp, $path);
        } elseif ($tmp !== false) {
            @unlink($tmp);
        }
    }

    private function now(): int
    {
        return (int) call_user_func($this->clock);
    }
}
