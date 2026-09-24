<?php

namespace Mervia\StoreConnector\Tests;

use Illuminate\Support\Facades\Blade;
use Illuminate\Support\Facades\Http;

class BladeDirectivesTest extends TestCase
{
    private const TEMPLATE = '<head>@merviaIncludeHead($product->id)</head><main>@merviaInclude($product->id)</main>';

    public function test_renders_both_parts_unescaped_with_one_request(): void
    {
        $head = '<script type="application/ld+json" id="mervia-faq-schema">{"q":"A & B <ok>"}</script>';
        $body = '<section id="mervia-shopping-guide"><p>Tom & Jerry</p></section>';
        Http::fake(['*' => Http::response(['version' => 1, 'head_html' => $head, 'body_html' => $body])]);

        $html = Blade::render(self::TEMPLATE, ['product' => (object) ['id' => 42]], deleteCachedView: true);

        $this->assertSame("<head>{$head}</head><main>{$body}</main>", $html);
        Http::assertSentCount(1);
    }

    public function test_prints_nothing_when_mervia_has_nothing(): void
    {
        Http::fake(['*' => Http::response(['error' => 'not_found'], 404)]);
        $this->assertSame('<head></head><main></main>', Blade::render(self::TEMPLATE, ['product' => (object) ['id' => 7]], deleteCachedView: true));
    }

    public function test_a_null_id_or_product_prints_nothing_instead_of_breaking_the_page(): void
    {
        Http::fake();
        $this->assertSame('<head></head><main></main>', Blade::render(self::TEMPLATE, ['product' => (object) ['id' => null]], deleteCachedView: true));
        $this->assertSame('<head></head><main></main>', Blade::render(self::TEMPLATE, ['product' => null], deleteCachedView: true));
        Http::assertNothingSent();
    }
}
