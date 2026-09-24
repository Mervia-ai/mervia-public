<?php

use PHPUnit\Framework\TestCase;

class MerviaWebhookSenderTest extends TestCase
{
    const SECRET = 's3cret-do-not-log';
    private $now = 1700000000;
    private $spool;

    public static function setUpBeforeClass(): void
    {
        LocalServer::start();
    }

    protected function setUp(): void
    {
        LocalServer::reset();
        $this->spool = sys_get_temp_dir() . '/mervia-spool-' . bin2hex(random_bytes(4));
    }

    private function sender(?string $url = null): MerviaWebhookSender
    {
        $now = &$this->now;
        return new MerviaWebhookSender($url === null ? LocalServer::$base . '/webhook' : $url, self::SECRET, $this->spool, array('clock' => function () use (&$now) { return $now; }));
    }

    private function payload(): array
    {
        return MerviaOrderEvent::build('order.paid', 'example-us', array(
            'id' => 1, 'paid_at' => '2026-09-23T10:00:00Z', 'currency' => 'USD', 'total' => '9.99',
            'line_items' => array(array('product_id' => 'p1', 'quantity' => 1, 'price' => '9.99')),
            'mervia_attribution' => 'v1.ü/x',
        ));
    }

    private function spooled(): array
    {
        return glob($this->spool . '/*.json') ?: array();
    }

    public function test_sends_signed_raw_json(): void
    {
        $payload = $this->payload();
        $this->assertTrue($this->sender()->send($payload));

        $got = LocalServer::log('webhook');
        $this->assertCount(1, $got);
        $this->assertSame('application/json', $got[0]['ct']);
        $this->assertSame((string) $this->now, $got[0]['ts']);
        $this->assertTrue(MerviaSigner::verify($got[0]['body'], self::SECRET, $got[0]['sig'], $got[0]['ts'], $this->now));
        $this->assertSame($payload, json_decode($got[0]['body'], true));
        $this->assertStringContainsString('"v1.ü/x"', $got[0]['body']);
        $this->assertSame(array(), $this->spooled());
    }

    public function test_failure_is_spooled_and_retried_with_backoff_and_fresh_timestamps(): void
    {
        LocalServer::set('webhook_status', '500');
        $sender = $this->sender();
        $this->assertFalse($sender->send($this->payload()));
        $this->assertCount(1, $this->spooled());

        $this->now += 59;
        $this->assertSame(array('sent' => 0, 'retrying' => 0, 'gave_up' => 0), $sender->retryPending(), 'not due yet');
        $this->now += 1;
        $this->assertSame(array('sent' => 0, 'retrying' => 1, 'gave_up' => 0), $sender->retryPending());
        $entry = json_decode(file_get_contents($this->spooled()[0]), true);
        $this->assertSame(2, $entry['attempts']);
        $this->assertSame($this->now + 120, $entry['next_attempt_at']);

        LocalServer::set('webhook_status', '200');
        $this->now += 120;
        $this->assertSame(array('sent' => 1, 'retrying' => 0, 'gave_up' => 0), $sender->retryPending());
        $this->assertSame(array(), $this->spooled());

        $got = LocalServer::log('webhook');
        $this->assertCount(3, $got);
        $this->assertCount(1, array_unique(array_map(function ($r) { return $r['body']; }, $got)), 'same bytes, same event_id');
        $this->assertCount(3, array_unique(array_map(function ($r) { return $r['ts']; }, $got)), 'each attempt re-signed now');
        foreach ($got as $r) {
            $this->assertTrue(MerviaSigner::verify($r['body'], self::SECRET, $r['sig'], $r['ts'], (int) $r['ts']));
        }
    }

    public function test_gives_up_after_12_attempts_inside_24_hours_without_logging_secrets(): void
    {
        LocalServer::set('webhook_status', '503');
        $log = tempnam(sys_get_temp_dir(), 'mervia-log');
        $previous = ini_set('error_log', $log);
        $start = $this->now;
        $sender = $this->sender();
        $sender->send($this->payload());
        foreach (MerviaWebhookSender::BACKOFF as $wait) {
            $this->now += $wait;
            $stats = $sender->retryPending();
        }
        ini_set('error_log', $previous);

        $this->assertSame(1, $stats['gave_up']);
        $this->assertCount(12, LocalServer::log('webhook'));
        $this->assertLessThan(86400, $this->now - $start);
        $this->assertSame(array(), $this->spooled());
        $this->assertCount(1, glob($this->spool . '/failed/*.json'));
        $logged = file_get_contents($log);
        $this->assertStringContainsString('gave up', $logged);
        $this->assertStringNotContainsString(self::SECRET, $logged);
        $this->assertStringNotContainsString('v1.', $logged);
    }

    public function test_enqueue_defers_to_the_next_run(): void
    {
        $sender = $this->sender();
        $sender->enqueue($this->payload());
        $this->assertSame(array(), LocalServer::log('webhook'));
        $this->assertSame(1, $sender->retryPending()['sent']);
        $this->assertCount(1, LocalServer::log('webhook'));
    }

    public function test_unreachable_endpoint_spools_instead_of_throwing(): void
    {
        $this->assertFalse($this->sender('http://127.0.0.1:1/webhook')->send($this->payload()));
        $this->assertCount(1, $this->spooled());
    }

    public function test_overlapping_runs_do_not_double_send(): void
    {
        $sender = $this->sender();
        $sender->enqueue($this->payload());
        $lock = fopen($this->spool . '/.lock', 'c');
        flock($lock, LOCK_EX);
        $this->assertSame(0, $sender->retryPending()['sent']);
        flock($lock, LOCK_UN);
        fclose($lock);
        $this->assertSame(1, $sender->retryPending()['sent']);
    }

    public function test_any_event_id_spools_safely(): void
    {
        LocalServer::set('webhook_status', '500');
        $payload = $this->payload();
        $payload['event_id'] = '../order:1042';
        $this->assertFalse($this->sender()->send($payload));
        $this->assertSame(array($this->spool . '/' . sha1('../order:1042') . '.json'), $this->spooled());
        $this->assertSame('660', substr(sprintf('%o', fileperms($this->spooled()[0])), -3));
    }

    public function test_corrupt_entry_is_parked_and_logged_not_skipped_forever(): void
    {
        mkdir($this->spool);
        file_put_contents($this->spool . '/bad.json', '{not json');
        $log = tempnam(sys_get_temp_dir(), 'mervia-log');
        $previous = ini_set('error_log', $log);
        $stats = $this->sender()->retryPending();
        ini_set('error_log', $previous);

        $this->assertSame(1, $stats['gave_up']);
        $this->assertFileExists($this->spool . '/failed/bad.json');
        $this->assertStringContainsString('corrupt', file_get_contents($log));
    }

    public function test_invalid_utf8_is_substituted(): void
    {
        $payload = $this->payload();
        $payload['order']['number'] = "#10\xB1";
        $this->assertTrue($this->sender()->send($payload));
        $this->assertStringContainsString("\u{FFFD}", LocalServer::log('webhook')[0]['body']);
    }

    public function test_payload_needs_an_event_id(): void
    {
        $this->expectException(InvalidArgumentException::class);
        $this->sender()->send(array('event' => 'order.paid'));
    }
}
