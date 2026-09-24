<?php

namespace Mervia\StoreConnector\Tests;

use Illuminate\Support\Facades\URL;
use Mervia\StoreConnector\Http\Resources\ArticleResource;
use Mervia\StoreConnector\Http\Resources\OrderResource;
use Mervia\StoreConnector\Http\Resources\PageResource;
use Mervia\StoreConnector\Http\Resources\ProductResource;
use Mervia\StoreConnector\Http\Resources\ReviewResource;
use Mervia\StoreConnector\Http\Resources\StoreResource;
use RuntimeException;

/** The resource stubs, fed a sparse model (optional columns null), must still match openapi.yaml. */
class ResourceSchemaTest extends TestCase
{
    private function assertMatches(string $component, $resource): array
    {
        $out = json_decode(json_encode($resource->resolve()), true);
        $this->assertSame([], SchemaCheck::errors($out, ['$ref' => "#/components/schemas/{$component}"], SchemaCheck::openapi()), $component);
        return $out;
    }

    protected function setUp(): void
    {
        parent::setUp();
        URL::forceRootUrl('https://www.example.com');
        URL::forceScheme('https');
    }

    public function test_store(): void
    {
        $store = ['name' => 'Example Store', 'primary_host' => 'www.example.com', 'hosts' => ['www.example.com'], 'currency' => 'USD', 'capabilities' => ['products']];
        $out = $this->assertMatches('Store', new StoreResource($store));
        $this->assertArrayNotHasKey('locale', $out);

        config(['mervia.store_id' => null]);
        $this->expectException(RuntimeException::class);
        (new StoreResource($store))->resolve();
    }

    public function test_product_with_sparse_columns(): void
    {
        $variant = (object) ['id' => 9, 'title' => null, 'sku' => null, 'barcode' => null, 'options' => null, 'price' => '129.5',
            'compare_at_price' => null, 'currency' => 'USD', 'available' => 1, 'stock' => null];
        $product = (object) ['id' => 42, 'slug' => 'widget', 'name' => 'Widget', 'description' => '<p>x</p>', 'brand' => null,
            'type' => null, 'tags' => null, 'status' => 'active', 'published_at' => null, 'created_at' => now(), 'updated_at' => now(),
            'images' => collect([(object) ['url' => 'https://cdn.example.com/a.jpg', 'alt' => null]]), 'variants' => collect([$variant])];

        $out = $this->assertMatches('Product', new ProductResource($product));
        $this->assertArrayNotHasKey('brand', $out);
        $this->assertArrayHasKey('published_at', $out);
        $this->assertSame('129.50', $out['variants'][0]['price']);
        $this->assertArrayHasKey('compare_at_price', $out['variants'][0]);
        $this->assertArrayNotHasKey('sku', $out['variants'][0]);
    }

    public function test_order_with_sparse_columns(): void
    {
        $item = (object) ['product_id' => 101, 'variant_id' => null, 'sku' => null, 'quantity' => '2', 'unit_price' => '64.75'];
        $order = (object) ['id' => 10042, 'number' => null, 'status' => 'paid', 'paid_at' => now(), 'updated_at' => now(), 'currency' => 'USD',
            'subtotal' => null, 'discount_total' => null, 'shipping_total' => 5, 'tax_total' => null, 'total' => 134.5, 'refunded_total' => null,
            'items' => collect([$item]), 'mervia_attribution' => null, 'email' => 'Buyer@Example.com'];

        $out = $this->assertMatches('Order', new OrderResource($order));
        $this->assertSame(['10042', 'paid', '134.50', '0.00', '5.00'], [$out['id'], $out['status'], $out['total'], $out['refunded_total'], $out['shipping']]);
        $this->assertArrayNotHasKey('number', $out);
        $this->assertArrayNotHasKey('subtotal', $out);
        $this->assertArrayHasKey('mervia_attribution', $out);
        $this->assertNull($out['mervia_attribution']);
        $this->assertSame(hash('sha256', 'buyer@example.com'), $out['customer_key']);
        $this->assertStringNotContainsString('example.com', json_encode($out));
        $this->assertSame(['product_id' => '101', 'variant_id' => null, 'quantity' => 2, 'price' => '64.75'], $out['line_items'][0]);
    }

    public function test_review_page_and_article(): void
    {
        $this->assertMatches('Review', new ReviewResource((object) ['id' => 1, 'rating' => 5, 'title' => null, 'body' => 'Great',
            'display_name' => null, 'verified' => true, 'created_at' => now()]));
        $this->assertMatches('Page', new PageResource((object) ['id' => 1, 'kind' => 'shipping', 'title' => 'Shipping', 'slug' => 'shipping',
            'body' => '<p>x</p>', 'updated_at' => now()]));
        $out = $this->assertMatches('Article', new ArticleResource((object) ['id' => 5, 'type' => 'post', 'title' => 'T', 'slug' => 't',
            'excerpt' => null, 'body_html' => '<p>x</p>', 'author' => null, 'tags' => null, 'featured_image_url' => null, 'meta_title' => null,
            'meta_description' => null, 'status' => 'hidden', 'published_at' => null, 'created_at' => now(), 'updated_at' => now()]));
        $this->assertArrayNotHasKey('author', $out);
        $this->assertArrayHasKey('featured_image_url', $out);
    }
}
