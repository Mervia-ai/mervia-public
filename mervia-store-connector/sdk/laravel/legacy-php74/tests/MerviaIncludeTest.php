<?php

use PHPUnit\Framework\TestCase;

class MerviaIncludeTest extends TestCase
{
    private $now = 1700000000;
    private $cacheDir;

    public static function setUpBeforeClass(): void
    {
        LocalServer::start();
    }

    protected function setUp(): void
    {
        LocalServer::reset();
        $this->cacheDir = sys_get_temp_dir() . '/mervia-cache-' . bin2hex(random_bytes(4));
    }

    /** A new instance per call models a new page request (the instance memoizes per request). */
    private function include(?string $url = null): MerviaInclude
    {
        $now = &$this->now;
        return new MerviaInclude($url === null ? LocalServer::$base . '/include/v1/sk' : $url, 'inc_key_123', $this->cacheDir, array('clock' => function () use (&$now) { return $now; }));
    }

    private function requests(): array
    {
        return LocalServer::log('include');
    }

    public function test_200_is_returned_and_cached_for_15_minutes(): void
    {
        $doc = $this->include()->fetch('a/b c');

        $this->assertStringContainsString('id="mervia-product-schema"', $doc['head_html']);
        $this->assertSame('<section id="mervia-shopping-guide">v1 &amp; more</section>', $doc['body_html']);
        $this->assertSame(array(array('raw_id' => 'a%2Fb%20c', 'auth' => 'Bearer inc_key_123', 'inm' => '')), $this->requests());

        $this->now += 899;
        $this->assertSame($doc, $this->include()->fetch('a/b c'));
        $this->assertCount(1, $this->requests());
    }

    public function test_304_after_expiry_reuses_the_copy_and_a_new_version_replaces_it(): void
    {
        $doc = $this->include()->fetch(42);
        $this->now += 901;
        $this->assertSame($doc, $this->include()->fetch(42));
        $this->assertSame('"v1"', $this->requests()[1]['inm']);

        LocalServer::set('version', '2');
        $this->now += 901;
        $this->assertStringContainsString('v2', $this->include()->fetch(42)['body_html']);
    }

    public function test_404_prints_nothing_and_drops_the_last_good_copy(): void
    {
        $this->include()->fetch(42);
        LocalServer::set('mode', 'gone');
        $this->now += 901;
        $this->assertSame(array('head_html' => '', 'body_html' => ''), $this->include()->fetch(42));

        LocalServer::set('mode', 'boom');
        $this->now += 901;
        $this->assertSame(array('head_html' => '', 'body_html' => ''), $this->include()->fetch(42));
    }

    public function test_timeout_serves_last_good_within_about_a_second_then_pauses(): void
    {
        $good = $this->include()->fetch(42);
        LocalServer::set('mode', 'slow');
        $this->now += 901;

        $t = microtime(true);
        $this->assertSame($good, $this->include()->fetch(42));
        $elapsed = microtime(true) - $t;
        $this->assertLessThan(1.6, $elapsed, 'the 1-second timeout must hold');
        $this->assertGreaterThan(0.9, $elapsed);

        $this->now += 30;
        $this->assertSame($good, $this->include()->fetch(42));
        $this->assertCount(2, $this->requests(), 'no new attempt inside the error window');

        usleep(800000); // let the server finish the slow request before the next test
    }

    public function test_error_with_no_copy_prints_nothing(): void
    {
        LocalServer::set('mode', 'boom');
        $this->expectOutputString('');
        $this->include()->printHead(42);
        $this->include()->printBody(42);
    }

    public function test_print_helpers_print_unescaped_and_share_one_request(): void
    {
        $inc = $this->include();
        ob_start();
        $inc->printHead(42);
        $inc->printBody(42);
        $out = ob_get_clean();
        $this->assertSame('<script type="application/ld+json" id="mervia-product-schema">{"v":1}</script><section id="mervia-shopping-guide">v1 &amp; more</section>', $out);
        $this->assertCount(1, $this->requests());
    }

    public function test_unreachable_server_and_unwritable_cache_print_nothing_and_raise_nothing(): void
    {
        $this->cacheDir = '/proc/mervia-cannot-write-here';
        $this->assertStringContainsString('v1', $this->include()->fetch(42)['body_html']);
        $this->assertSame(array('head_html' => '', 'body_html' => ''), $this->include('http://127.0.0.1:1/include/v1/sk')->fetch(42));
    }

    public function test_unconfigured_or_bad_input_makes_no_request(): void
    {
        $this->assertSame('', (new MerviaInclude('', 'k', $this->cacheDir))->fetch(1)['body_html']);
        $this->assertSame('', (new MerviaInclude(LocalServer::$base, null, $this->cacheDir))->fetch(1)['body_html']);
        $this->assertSame('', $this->include()->fetch(null)['body_html']);
        $this->assertSame(array(), $this->requests());
    }
}
