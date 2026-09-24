<?php

namespace Mervia\StoreConnector\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;
use RuntimeException;

/**
 * GET /store (item 1). Usually built from config rather than a model:
 *
 *   return new StoreResource([
 *       'name' => 'Example Store', 'primary_host' => 'www.example.com',
 *       'hosts' => ['www.example.com', 'example.com'], 'currency' => 'USD',
 *       'locale' => 'en-US', 'timezone' => 'America/Los_Angeles',
 *       'capabilities' => ['products', 'reviews', 'articles', 'pages', 'orders', 'content_push'],
 *   ]);
 *
 * Declare only what you have built: Mervia enables exactly these capabilities. The default set
 * is products, reviews, articles, pages, orders and content_push; order_webhook, product_webhook
 * and content_pull only by arrangement with Mervia (content_pull never with content_push).
 */
class StoreResource extends JsonResource
{
    public static $wrap = null;

    public function toArray(Request $request): array
    {
        $storeId = (string) config('mervia.store_id'); // must never change for this store
        if ($storeId === '') {
            throw new RuntimeException('Set MERVIA_STORE_ID: GET /store must return a store_id');
        }
        return Shape::compact([
            'store_id' => $storeId,
            'name' => $this->resource['name'],
            'primary_host' => $this->resource['primary_host'],
            'hosts' => $this->resource['hosts'],
            'currency' => $this->resource['currency'],
            'locale' => $this->resource['locale'] ?? null,
            'timezone' => $this->resource['timezone'] ?? null,
            'capabilities' => $this->resource['capabilities'],
        ]);
    }
}
