<?php

namespace Mervia\StoreConnector\Tests;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Facades\Queue;
use Mervia\StoreConnector\Webhook\OrderEvent;
use Mervia\StoreConnector\Webhook\SendWebhook;
use Mervia\StoreConnector\Webhook\Signer;
use RuntimeException;

class SendWebhookTest extends TestCase
{
    private function payload(): array
    {
        return OrderEvent::paid(
            storeId: 'example-us', id: 1, paidAt: '2026-09-23T10:00:00Z', currency: 'USD', total: '9.99',
            lineItems: [['product_id' => 'p1', 'quantity' => 1, 'price' => '9.99']], merviaAttribution: 'v1.ü/x',
        );
    }

    public function test_posts_signed_raw_json_and_succeeds_on_2xx(): void
    {
        Http::fake(['hooks.mervia.test/*' => Http::response('', 202)]);
        $payload = $this->payload();

        (new SendWebhook($payload))->handle();

        Http::assertSentCount(1);
        Http::assertSent(function (Request $request) use ($payload) {
            $ts = (int) $request->header('X-Mervia-Timestamp')[0];
            $tsHeader = $request->header('X-Mervia-Timestamp')[0];
            return $request->url() === 'https://hooks.mervia.test/v1/orders'
                && $request->method() === 'POST'
                && $request->hasHeader('Content-Type', 'application/json')
                && abs(time() - $ts) < 5
                && Signer::verify($request->body(), 's3cret-do-not-log', $request->header('X-Mervia-Signature')[0], $tsHeader)
                && json_decode($request->body(), true) === $payload
                && str_contains($request->body(), '"v1.ü/x"'); // unescaped, signed as sent
        });
    }

    public function test_non_2xx_throws_so_the_queue_retries_without_leaking_the_secret(): void
    {
        Http::fake(['*' => Http::response('nope', 500)]);

        try {
            (new SendWebhook($this->payload()))->handle();
            $this->fail('expected an exception');
        } catch (RuntimeException $e) {
            $this->assertStringContainsString('HTTP 500', $e->getMessage());
            $this->assertStringNotContainsString('s3cret-do-not-log', $e->getMessage());
        }
    }

    public function test_connection_failure_throws_without_request_details(): void
    {
        Http::fake(fn () => throw new ConnectionException('cURL error 28 for https://hooks.mervia.test/v1/orders?secret=s3cret-do-not-log'));

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessageMatches('/^Mervia webhook order\.paid [0-9a-f-]+ could not be delivered \(.*ConnectionException\)$/');
        (new SendWebhook($this->payload()))->handle();
    }

    public function test_invalid_utf8_is_substituted_not_retried_forever(): void
    {
        Http::fake(['*' => Http::response('', 200)]);
        $payload = $this->payload();
        $payload['order']['number'] = "#10\xB1";

        (new SendWebhook($payload))->handle();

        Http::assertSent(fn (Request $r) => str_contains($r->body(), "\u{FFFD}")
            && Signer::verify($r->body(), 's3cret-do-not-log', $r->header('X-Mervia-Signature')[0], $r->header('X-Mervia-Timestamp')[0]));
    }

    public function test_redirect_or_client_error_is_not_success(): void
    {
        Http::fake(['*' => Http::response('', 401)]);
        $this->expectException(RuntimeException::class);
        (new SendWebhook($this->payload()))->handle();
    }

    public function test_missing_configuration_throws(): void
    {
        config(['mervia.webhook_secret' => null]);
        Http::fake();
        $this->expectExceptionMessage('MERVIA_WEBHOOK_SECRET');
        (new SendWebhook($this->payload()))->handle();
    }

    public function test_retry_schedule_spans_about_a_day(): void
    {
        $job = new SendWebhook($this->payload());
        $waits = $job->backoff();

        $this->assertSame(12, $job->tries);
        $this->assertCount($job->tries - 1, $waits);
        $this->assertSame($waits, array_values(array_unique($waits)), 'strictly growing');
        $this->assertGreaterThan(20 * 3600, array_sum($waits));
        $this->assertLessThanOrEqual(24 * 3600, array_sum($waits));
    }

    public function test_is_queued(): void
    {
        Queue::fake();
        SendWebhook::dispatch($this->payload());
        Queue::assertPushed(SendWebhook::class, fn (SendWebhook $job) => $job->payload['event'] === 'order.paid');
    }

    public function test_failed_logs_ids_only(): void
    {
        Log::spy();
        $payload = $this->payload();

        (new SendWebhook($payload))->failed(new RuntimeException('Mervia webhook order.paid x was answered with HTTP 500'));

        Log::shouldHaveReceived('error')->once()->withArgs(function (string $message, array $context) use ($payload) {
            $all = $message . json_encode($context);
            return $context['event_id'] === $payload['event_id']
                && !str_contains($all, 's3cret-do-not-log')
                && !str_contains($all, 'v1.') // no payload contents
                && !array_key_exists('payload', $context);
        });
    }
}
