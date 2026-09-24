<?php

namespace Mervia\StoreConnector\Webhook;

use Illuminate\Bus\Queueable;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Bus\Dispatchable;
use Illuminate\Queue\InteractsWithQueue;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use RuntimeException;
use Throwable;

/**
 * Sends one by-arrangement signed webhook (order or product event) from the queue, retrying for about 24 hours.
 *
 *   SendWebhook::dispatch(OrderEvent::paid(...));
 *
 * Each attempt signs the raw JSON body afresh with the current timestamp (Mervia rejects a
 * timestamp more than 5 minutes old); the event_id stays the same, so a delivery Mervia
 * already accepted is ignored. 2xx is success; anything else, or no answer, throws so the
 * queue retries. Neither the secret nor the payload is ever logged.
 */
class SendWebhook implements ShouldQueue
{
    use Dispatchable;
    use InteractsWithQueue;
    use Queueable;

    /** 12 attempts; the waits below add up to about 22 hours, so the last try lands inside 24 h. */
    public int $tries = 12;

    public function __construct(public readonly array $payload)
    {
    }

    /** Seconds to wait before attempts 2..12. */
    public function backoff(): array
    {
        return [60, 120, 300, 600, 1200, 1800, 3600, 7200, 14400, 21600, 28800];
    }

    public function handle(): void
    {
        $url = (string) config('mervia.webhook_url');
        $secret = (string) config('mervia.webhook_secret');
        if ($url === '' || $secret === '') {
            throw new RuntimeException('Mervia webhook is not configured: set MERVIA_WEBHOOK_URL and MERVIA_WEBHOOK_SECRET');
        }

        $body = json_encode($this->payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE | JSON_THROW_ON_ERROR);
        $headers = Signer::sign($body, $secret, time());

        try {
            $response = Http::withHeaders($headers)
                ->timeout((int) config('mervia.webhook_timeout_seconds', 10))
                ->withBody($body, 'application/json')
                ->post($url);
        } catch (Throwable $e) {
            // Connection errors carry request details; report only the class.
            throw new RuntimeException('Mervia webhook ' . $this->describe() . ' could not be delivered (' . $e::class . ')');
        }

        if (!$response->successful()) {
            throw new RuntimeException('Mervia webhook ' . $this->describe() . ' was answered with HTTP ' . $response->status());
        }
    }

    public function failed(?Throwable $e): void
    {
        Log::error('Mervia webhook gave up after all retries', [
            'event' => $this->payload['event'] ?? null,
            'event_id' => $this->payload['event_id'] ?? null,
            'reason' => $e?->getMessage(),
        ]);
    }

    private function describe(): string
    {
        return ($this->payload['event'] ?? 'event') . ' ' . ($this->payload['event_id'] ?? '');
    }
}
