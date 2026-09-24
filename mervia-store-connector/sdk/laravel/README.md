# mervia/store-connector-laravel

Laravel helpers for the [Mervia Store Connector](../../README.md): the orders list response
(item 8), the product-page content store and print (item 6), the attribution cookie read at
checkout (items 7, 8), plus stubs for every endpoint Mervia calls. Your store never calls Mervia;
the helpers for the by-arrangement webhooks and pull include are listed last.

| Helper | Item | What it does |
| --- | --- | --- |
| `Http\Resources\OrderResource`, `OrderLineItemResource` | 8 | Shape a paid order exactly as `GET /orders` returns it (`contract/schemas/order.schema.json`); hashes the email into `customer_key`, never returns it |
| `Content\ProductContent` + `@merviaContentHead` / `@merviaContent` | 6 | Keeps the document Mervia pushes to `PUT /products/{id}/content` (version rule, `DELETE`), prints it verbatim on the server |
| `Attribution\Cookie` | 7, 8 | Reads the raw `mervia_attr` cookie at checkout so you can store it on the order |
| `mervia.auth` middleware, FormRequests, JsonResources | 1, 2, 3, 4, 5, 6, 8 | Stubs for the endpoints you serve — see [`src/Http/Controllers/README.md`](src/Http/Controllers/README.md) |
| `Webhook\OrderEvent`, `Webhook\ProductEvent`, `Webhook\SendWebhook` | by arrangement | Only for a store that has arranged `order_webhook` / `product_webhook` with Mervia: build the events and send them signed (`timestamp.body`, HMAC-SHA256), retrying with backoff for about 24 hours |
| `Include\Fetcher` + `@merviaIncludeHead` / `@merviaInclude` | by arrangement | Only for a store that has arranged the pull alternative to item 6: fetches the document itself (1 s timeout, 15 min cache, last good copy) |

## Requirements

PHP 8.1+ and Laravel 10, 11, 12 or 13. Laravel 10 and 11 no longer receive security fixes, and
current Composer releases refuse to install them by default because of open security advisories; prefer 12 or 13.

**On PHP 7.4?** This package will not install. Use the dependency-free plain-PHP versions of
the helpers in [`legacy-php74/`](legacy-php74/) (curl and PDO, no framework), and move to this
package once the site runs PHP 8.1 or later.

## Install

```bash
composer require mervia/store-connector-laravel
php artisan vendor:publish --tag=mervia-config   # optional: copies config/mervia.php
php artisan migrate                              # creates mervia_product_content (item 6)
```

The service provider is auto-discovered, and its migration runs with yours (publish it with
`--tag=mervia-migrations` to keep a copy in your repository).

## Configuration

All values come from `.env`. None of them may appear in page HTML.

| Variable | Used by | Notes |
| --- | --- | --- |
| `MERVIA_STORE_ID` | webhooks, `StoreResource` | the `store_id` your `GET /store` returns; never changes |
| `MERVIA_API_KEY`, `MERVIA_API_KEY_PREVIOUS` | `mervia.auth` | the key(s) you issued to Mervia; two for rotation |
| `MERVIA_WEBHOOK_URL`, `MERVIA_WEBHOOK_SECRET` | `SendWebhook` (by arrangement only) | from your integration document |
| `MERVIA_WEBHOOK_TIMEOUT_SECONDS` | `SendWebhook` | default 10 |
| `MERVIA_CONTENT_TABLE` | `ProductContent` | table for the pushed product-page document; default `mervia_product_content` |
| `MERVIA_INCLUDE_URL` | `Fetcher` (pull alternative only) | base including your store key, e.g. `https://app.mervia.ai/include/v1/{store_key}` |
| `MERVIA_INCLUDE_KEY` | `Fetcher` (pull alternative only) | the include key (server-side only) |
| `MERVIA_INCLUDE_TIMEOUT_SECONDS` | `Fetcher` | default 1 (contract value) |
| `MERVIA_INCLUDE_CACHE_SECONDS` | `Fetcher` | default 900 (contract value) |
| `MERVIA_INCLUDE_ERROR_CACHE_SECONDS` | `Fetcher` | default 60: after an error, serve the last good copy this long before trying again (not in the contract; a guard so an outage costs one slow request per product per minute) |
| `MERVIA_INCLUDE_CACHE_STORE` | `Fetcher` | a cache store name; default is your default store |
| `MERVIA_TAG_STORE_ID` | your layout | the store id in the tracking tag snippet (item 7) |

## Product page (item 6)

Mervia sends each product's document (structured data for `<head>`, the shopping guide for the
page) to `PUT /products/{id}/content` under the API key you issued, and removes it with
`DELETE`. Two routes keep it, two directives print it:

```php
// routes/api.php, inside the mervia/v1 group (see src/Http/Controllers/README.md)
Route::put('/products/{id}/content', function (PutProductContentRequest $request, string $id, ProductContent $content) {
    abort_unless(Product::whereKey($id)->exists(), 404, 'not_found');
    $content->store($id, $request->validated());   // false when an older version was ignored
    return response()->noContent();
});
Route::delete('/products/{id}/content', function (string $id, ProductContent $content) {
    $content->remove($id);                         // nothing stored is fine
    return response()->noContent();
});
```

```blade
{{-- layouts/app.blade.php, inside <head> --}}
@isset($product) @merviaContentHead($product->id) @endisset

{{-- products/show.blade.php, where the shopping guide should appear --}}
@merviaContent($product->id)
```

`@merviaContentHead` prints the stored `head_html` (the `application/ld+json` blocks) and
`@merviaContent` the stored `body_html` (the `<section id="mervia-shopping-guide">`), both
unescaped and unchanged, rendered on the server so crawlers and AI assistants see them in the
HTML. They share one lookup per product per request, never throw, and print nothing when no
document is stored (or the expression fails, say `$product` is null), so the page renders as
before Mervia. The document lives in the `mervia_product_content` table from the package
migration; bind your own `Content\ProductContentStore` to keep it elsewhere. In code:
`app(ProductContent::class)->head($id)` / `->body($id)`.

### Pull alternative, by arrangement only

If you have agreed the pull option with Mervia (your store declares `content_pull` and fetches
the document from Mervia's include route with an include key), use the include directives
instead: `@merviaIncludeHead($product->id)` inside `<head>` and `@merviaInclude($product->id)`
where the guide goes. `Include\Fetcher` applies the contract's rules (1-second timeout,
15-minute cache per product, the last good copy on any error, nothing when there is none) and
shares one fetch per product per request. Use a cache store that survives deploys so the last
good copy does; `app(Fetcher::class)->fetch($id)` never throws. Keep the include key out of
page HTML.

## Attribution cookie at checkout

Mervia's tracking tag sets `mervia_attr` in the browser. Copy its raw value onto the order when
the order is created, while you still have the shopper's request:

```php
use Mervia\StoreConnector\Attribution\Cookie;

$order->mervia_attribution = Cookie::forOrder();   // string or null; do not parse it
```

(A nullable `text` column on your orders table.) The value is read verbatim from the `Cookie`
header, without URL-decoding, so it reaches Mervia exactly as the tag wrote it. The cookie is
not encrypted, so the service
provider adds it to Laravel's `EncryptCookies` exceptions on Laravel 11+. On Laravel 10 add it
yourself in `app/Http/Middleware/EncryptCookies.php`: `protected $except = ['mervia_attr'];`
(`Cookie::raw()` reads the header first anyway; the exception keeps `$request->cookie()` honest too.)

## Orders endpoint (item 8)

Mervia reads `GET /orders` about once an hour and attributes the orders to AI-referred sessions
through `mervia_attribution`. List only orders that have been **paid**, ordered by `updated_at`,
honour `updated_since` and `limit`/`cursor`, and shape each one with `OrderResource`:

```php
public function orders(Request $request)
{
    $page = Order::query()->whereNotNull('paid_at')
        ->when($request->query('updated_since'), fn ($q, $since) => $q->where('updated_at', '>=', $since))
        ->orderBy('updated_at')->orderBy('id')
        ->cursorPaginate(min((int) $request->query('limit', 250), 250));
    return ['items' => OrderResource::collection($page->items())->resolve(), 'next_cursor' => $page->nextCursor()?->encode()];
}
```

`OrderResource` has `TODO` markers for your columns. `updated_at` must change when the order is
paid, refunded or cancelled; `status` is `paid`, `refunded` or `cancelled`; `refunded_total` is
the running total refunded so far (`"0.00"` until something is) and a cancelled order counts as
a full refund. Mervia keeps the amounts from the first time it reads the order as paid. The
resource never returns a name, email, phone or address: the email becomes `customer_key`, a
SHA-256, and only if you have it.

## Webhooks, by arrangement only (`order_webhook`, `product_webhook`)

By default no store sends webhooks. If you have arranged them with Mervia, dispatch from wherever
your order becomes paid, refunded or cancelled (the event carries the same order object as
`GET /orders`; `status` follows the event, `refundedTotal:` is required on a refund):

```php
use Mervia\StoreConnector\Webhook\OrderEvent;
use Mervia\StoreConnector\Webhook\SendWebhook;

SendWebhook::dispatch(OrderEvent::paid(
    storeId: config('mervia.store_id'),
    id: $order->id,
    number: $order->number,
    paidAt: $order->paid_at,                 // DateTimeInterface or ISO 8601 with timezone
    currency: $order->currency,
    subtotal: $order->subtotal,
    discountTotal: $order->discount_total,
    shipping: $order->shipping_total,
    tax: $order->tax_total,
    total: $order->total,                    // what the customer paid
    lineItems: $order->items->map(fn ($i) => [
        'product_id' => $i->product_id, 'variant_id' => $i->variant_id,
        'sku' => $i->sku, 'quantity' => $i->quantity, 'price' => $i->unit_price,
    ])->all(),
    merviaAttribution: $order->mervia_attribution,   // stored at checkout; null when absent
    customerKey: OrderEvent::customerKey($order->email),  // optional: a SHA-256, never the email
));
```

`OrderEvent::refunded(...)` (with `refundedTotal:`) and `OrderEvent::cancelled(...)` take the
same arguments. Send `paid` once per order: the first `order.paid` fixes the amounts, and a
later one for the same id with different totals is treated as a duplicate. A change after
payment goes out as `refunded` with the new **cumulative** `refundedTotal:` (not the delta);
`cancelled` counts as a full refund. Mervia refuses a body over 256 KB, which an order event
never approaches unless every line-item attribute is sent. Money is a decimal string (sent padded to two decimals: `"129.5"` becomes
`"129.50"`, a three-decimal `"1.250"` stays exact) or an int/float in whole units (not cents; a
float with more than two decimals is refused). Timestamps need seconds and a timezone.
Customer names, emails, phones and addresses are never sent: a key containing `email`, `name`,
`phone` or `address`, or an email-shaped value, in `extra:` or a line item is refused with an
exception.

`SendWebhook` signs the exact JSON bytes it sends together with the timestamp
(`X-Mervia-Timestamp: <unix seconds>`, `X-Mervia-Signature: sha256=<hex HMAC-SHA256 of
"<timestamp>.<body>">`), re-signing on every attempt with a fresh timestamp; the `event_id`
stays the same so Mervia ignores a repeat. Signing the timestamp is what makes Mervia's 5-minute
window a real replay defence. Invalid UTF-8 in a field is sent as
U+FFFD rather than failing for a day. `2xx` is success; anything else is retried
12 times over about 22 hours (1 min, 2, 5, 10, 20, 30 min, 1 h, 2 h, 4 h, 6 h, 8 h). Run a real
queue worker: with `QUEUE_CONNECTION=sync` a Mervia outage would surface as an exception in your
checkout. Neither the secret nor the payload is logged.

Product changes (item 11, optional): `SendWebhook::dispatch(ProductEvent::updated(config('mervia.store_id'), $product->id, $product->updated_at))`
from a model observer; `ProductEvent::deleted(...)` on delete.

## Endpoint stubs

`Http/Resources/*Resource.php` map a generic Eloquent shape to the contract; each has `TODO`
markers where your column names go. `Http/Requests/*Request.php` validate the three write
bodies and answer `422` in the contract's error shape. Route list, the `mervia.auth` middleware,
hidden-article rules and `preview_url`: [`src/Http/Controllers/README.md`](src/Http/Controllers/README.md).
Verify the result with the conformance checker (`checker/`).

## Tests

No local PHP needed; run everything in Docker from `sdk/laravel/`. The tests read the JSON
Schemas in `contract/`, so mount the repository root:

```bash
docker run --rm -v "$PWD":/app -w /app composer:2 composer install
docker run --rm -v "$PWD/../..":/repo -w /repo/sdk/laravel composer:2 vendor/bin/phpunit
```

That runs on the newest Laravel the `composer:2` image resolves. To check an older pair, pin
the platform and Laravel in a scratch copy, e.g. Laravel 10 on PHP 8.1:

```bash
composer config platform.php 8.1.30 && composer config policy.advisories.block false
composer require --no-update 'illuminate/support:^10.0' && composer update
docker run --rm -v "$PWD/../..":/repo -w /repo/sdk/laravel php:8.1-cli vendor/bin/phpunit
```
