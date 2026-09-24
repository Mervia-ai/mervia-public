<?php

namespace Mervia\StoreConnector\Tests;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Blade;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Route;
use Mervia\StoreConnector\Content\ProductContent;
use Mervia\StoreConnector\Content\ProductContentStore;
use Mervia\StoreConnector\Http\Requests\PutProductContentRequest;
use RuntimeException;

class ProductContentTest extends TestCase
{
    use RefreshDatabase;

    private const HEAD = '<script type="application/ld+json" id="mervia-product-schema">{"@type":"Product","name":"A & B <ok>"}</script>';
    private const BODY = '<section id="mervia-shopping-guide"><p>Tom & Jerry</p></section>';
    private const TEMPLATE = '<head>@merviaContentHead($product->id)</head><main>@merviaContent($product->id)</main>';

    protected function defineEnvironment($app): void
    {
        parent::defineEnvironment($app);
        $app['config']->set('database.default', 'testing');
    }

    protected function defineRoutes($router): void
    {
        Route::prefix('api/mervia/v1')->middleware('mervia.auth')->group(function () {
            Route::put('/products/{id}/content', function (PutProductContentRequest $r, string $id, ProductContent $c) {
                $c->store($id, $r->validated());
                return response()->noContent();
            });
            Route::delete('/products/{id}/content', function (string $id, ProductContent $c) {
                $c->remove($id);
                return response()->noContent();
            });
        });
    }

    private function content(): ProductContent
    {
        return app(ProductContent::class);
    }

    public function test_stores_and_prints_the_document_verbatim(): void
    {
        $this->assertTrue($this->content()->store(42, ['version' => 3, 'head_html' => self::HEAD, 'body_html' => self::BODY]));

        $fresh = new ProductContent(app(ProductContentStore::class)); // a new request: no memo
        $this->assertSame(['version' => 3, 'head_html' => self::HEAD, 'body_html' => self::BODY], $fresh->fetch('42'));
        $this->assertSame(self::HEAD, $fresh->head(42));
        $this->assertSame(1, DB::table('mervia_product_content')->count());
    }

    public function test_a_lower_version_is_ignored_and_an_equal_or_higher_one_replaces(): void
    {
        $c = $this->content();
        $c->store(1, ['version' => 5, 'head_html' => 'h5', 'body_html' => 'b5']);
        $this->assertFalse($c->store(1, ['version' => 4, 'head_html' => 'h4', 'body_html' => 'b4']));
        $this->assertSame('b5', $c->body(1));
        $this->assertTrue($c->store(1, ['version' => 5, 'head_html' => 'h5x', 'body_html' => 'b5x']));
        $this->assertSame('b5x', $c->body(1));
        $this->assertTrue($c->store(1, ['version' => 6, 'head_html' => '', 'body_html' => 'b6']));
        $this->assertSame(['version' => 6, 'head_html' => '', 'body_html' => 'b6'], $c->fetch(1));
    }

    public function test_remove_empties_the_page_and_is_fine_when_nothing_is_stored(): void
    {
        $c = $this->content();
        $c->store(7, ['version' => 1, 'head_html' => 'h', 'body_html' => 'b']);
        $c->remove(7);
        $this->assertSame(['version' => null, 'head_html' => '', 'body_html' => ''], $c->fetch(7));
        $c->remove(7);
        $c->remove('never-stored');
        $this->assertSame('', $c->body('never-stored'));
    }

    public function test_reading_never_throws(): void
    {
        $broken = new ProductContent(new class implements ProductContentStore {
            public function get(string $productId): ?array { throw new RuntimeException('db down'); }
            public function put(string $productId, int $version, string $headHtml, string $bodyHtml): void {}
            public function delete(string $productId): void {}
        });
        $this->assertSame('', $broken->head(1));
        $this->assertSame('', $this->content()->body(null));
        $this->assertSame('', $this->content()->body(''));
    }

    public function test_blade_directives_print_unescaped_with_one_lookup_and_nothing_when_absent(): void
    {
        $this->content()->store(42, ['version' => 1, 'head_html' => self::HEAD, 'body_html' => self::BODY]);
        app()->forgetInstance(ProductContent::class); // a fresh singleton, as on a new request
        DB::enableQueryLog();

        $html = Blade::render(self::TEMPLATE, ['product' => (object) ['id' => 42]], deleteCachedView: true);

        $this->assertSame('<head>' . self::HEAD . '</head><main>' . self::BODY . '</main>', $html);
        $this->assertCount(1, DB::getQueryLog());
        $this->assertSame('<head></head><main></main>', Blade::render(self::TEMPLATE, ['product' => (object) ['id' => 99]], deleteCachedView: true));
        $this->assertSame('<head></head><main></main>', Blade::render(self::TEMPLATE, ['product' => null], deleteCachedView: true));
    }

    public function test_the_put_and_delete_endpoints_round_trip(): void
    {
        $auth = ['Authorization' => 'Bearer key-current'];
        $this->putJson('/api/mervia/v1/products/9/content', ['version' => 2, 'head_html' => self::HEAD, 'body_html' => self::BODY], $auth)->assertNoContent();
        $this->assertSame(self::BODY, (new ProductContent(app(ProductContentStore::class)))->body(9));

        $this->putJson('/api/mervia/v1/products/9/content', ['version' => 1, 'head_html' => '', 'body_html' => 'old'], $auth)->assertNoContent();
        $this->assertSame(self::BODY, (new ProductContent(app(ProductContentStore::class)))->body(9), 'the older version was ignored');

        $this->deleteJson('/api/mervia/v1/products/9/content', [], $auth)->assertNoContent();
        $this->assertSame('', (new ProductContent(app(ProductContentStore::class)))->body(9));
        $this->deleteJson('/api/mervia/v1/products/9/content', [], $auth)->assertNoContent();
        $this->putJson('/api/mervia/v1/products/9/content', ['version' => 1, 'head_html' => '', 'body_html' => ''])->assertStatus(401);
    }
}
