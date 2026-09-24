<?php

namespace Mervia\StoreConnector\Tests;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Mervia\StoreConnector\Include\Fetcher;

class FetcherTest extends TestCase
{
    private const DOC = ['version' => 3, 'head_html' => '<script type="application/ld+json" id="mervia-product-schema">{}</script>', 'body_html' => '<section id="mervia-shopping-guide">Guide</section>'];
    private const EMPTY = ['head_html' => '', 'body_html' => ''];

    private function fetch(string|int $id = 42): array
    {
        return app(Fetcher::class)->fetch($id);
    }

    public function test_requests_carry_a_one_second_timeout(): void
    {
        $this->assertSame(900, config('mervia.include_cache_seconds'));
        $seen = null;
        Http::fake(function ($request, array $options) use (&$seen) {
            $seen = $options;
            return Http::response(self::DOC);
        });

        $this->fetch();

        $this->assertSame(1.0, $seen['timeout']);
        $this->assertSame(1.0, $seen['connect_timeout']);
    }

    public function test_a_failing_cache_still_serves_the_fetched_document(): void
    {
        Http::fake(['*' => Http::response(self::DOC)]);
        $broken = \Mockery::mock(\Illuminate\Contracts\Cache\Repository::class);
        $broken->shouldReceive('get', 'put', 'forever', 'forget')->andThrow(new \RuntimeException('redis down'));
        \Illuminate\Support\Facades\Cache::shouldReceive('store')->andReturn($broken);

        $this->assertSame(self::DOC['body_html'], $this->fetch()['body_html']);
    }

    public function test_200_is_returned_and_cached_for_15_minutes(): void
    {
        Http::fake(['*' => Http::response(self::DOC, 200, ['ETag' => '"v3"'])]);

        $this->assertSame(['head_html' => self::DOC['head_html'], 'body_html' => self::DOC['body_html']], $this->fetch());
        $this->travel(899)->seconds();
        $this->fetch();

        Http::assertSentCount(1);
        Http::assertSent(fn (Request $r) => $r->url() === 'https://app.mervia.test/include/v1/sk_example/products/42'
            && $r->header('Authorization') === ['Bearer inc_key_123']);

        $this->travel(2)->seconds();
        $this->fetch();
        Http::assertSentCount(2);
    }

    public function test_product_id_is_url_encoded(): void
    {
        Http::fake(['*' => Http::response(self::DOC)]);
        $this->fetch('a/b c');
        Http::assertSent(fn (Request $r) => str_ends_with($r->url(), '/products/a%2Fb%20c'));
    }

    public function test_404_prints_nothing_caches_it_and_drops_the_last_good_copy(): void
    {
        Http::fakeSequence()
            ->push(self::DOC)
            ->push(['error' => 'not_found'], 404)
            ->push('', 500);

        $this->assertNotSame(self::EMPTY, $this->fetch());
        $this->travel(901)->seconds();
        $this->assertSame(self::EMPTY, $this->fetch());
        $this->assertSame(self::EMPTY, $this->fetch());
        Http::assertSentCount(2);

        $this->travel(901)->seconds();
        $this->assertSame(self::EMPTY, $this->fetch(), 'a removed guide must not come back from last-good on an error');
    }

    public function test_timeout_serves_last_good_and_backs_off_for_a_minute(): void
    {
        $calls = 0;
        Http::fake(function () use (&$calls) {
            if (++$calls === 1) {
                return Http::response(self::DOC);
            }
            throw new ConnectionException('Operation timed out after 1000 milliseconds');
        });

        $good = $this->fetch();
        $this->travel(901)->seconds();

        $this->assertSame($good, $this->fetch());
        $this->assertSame($good, $this->fetch());
        $this->assertSame(2, $calls, 'no second attempt inside the error window');

        $this->travel(61)->seconds();
        $this->assertSame($good, $this->fetch());
        $this->assertSame(3, $calls);
    }

    public function test_error_with_no_last_good_prints_nothing(): void
    {
        Http::fake(['*' => Http::response('<html>502</html>', 502)]);
        $this->assertSame(self::EMPTY, $this->fetch());
    }

    public function test_malformed_200_is_treated_as_an_error(): void
    {
        Http::fakeSequence()->push(self::DOC)->push(['head_html' => 1]);
        $good = $this->fetch();
        $this->travel(901)->seconds();
        $this->assertSame($good, $this->fetch());
    }

    public function test_304_reuses_the_cached_copy(): void
    {
        Http::fakeSequence()
            ->push(self::DOC, 200, ['ETag' => '"v3"'])
            ->push('', 304, ['ETag' => '"v3"']);

        $good = $this->fetch();
        $this->travel(901)->seconds();

        $this->assertSame($good, $this->fetch());
        Http::assertSent(fn (Request $r) => $r->header('If-None-Match') === ['"v3"']);
        $this->travel(899)->seconds();
        $this->fetch();
        Http::assertSentCount(2);
    }

    public function test_unconfigured_or_bad_input_prints_nothing_without_a_request(): void
    {
        Http::fake();
        $this->assertSame(self::EMPTY, app(Fetcher::class)->fetch(null));
        $this->assertSame(self::EMPTY, app(Fetcher::class)->fetch(''));
        config(['mervia.include_key' => null]);
        $this->assertSame(self::EMPTY, $this->fetch());
        Http::assertNothingSent();
    }
}
