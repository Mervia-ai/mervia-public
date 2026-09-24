# Mervia helpers for PHP 7.4 (no framework)

Plain-PHP versions of the store-side helpers for sites that cannot yet run the Laravel
package (PHP 8.1+), such as a site on PHP 7.4: the orders list response (item 8), the
product-page content store and print (item 6), and the attribution cookie read at checkout
(items 7, 8), plus, by arrangement with Mervia only, the signed webhook sender and the pull
include. They need only `ext-json` (`ext-pdo` for the product-page document table, `ext-curl`
for the by-arrangement helpers), and behave exactly like the Laravel versions. Copy this folder
into the site and:

```php
require_once __DIR__ . '/mervia/mervia.php';
```

| File | Item | What it does |
| --- | --- | --- |
| `MerviaOrders.php` | 8 | `GET /orders`: turns your paid-order rows into the contract's list response, with `limit`/`cursor` and `updated_since` through a query callback you supply |
| `MerviaOrderEvent.php` | 8 | `MerviaOrderEvent::order($row)` normalises one order (money, timestamps, ids) and refuses customer personal data; also builds the by-arrangement webhook payloads |
| `MerviaProductContent.php` | 6 | Product-page content: handles `PUT`/`DELETE /products/{id}/content` with the version rule, keeps the document (PDO table or your callbacks), prints it verbatim |
| `MerviaAttributionCookie.php` | 7, 8 | Raw `mervia_attr` cookie value to store on the order |
| `MerviaSigner.php`, `MerviaWebhookSender.php` | by arrangement | Only for a store that has arranged `order_webhook` / `product_webhook`: signs `timestamp.body` and sends; failures go to a spool directory that a cron job retries for up to 24 h |
| `MerviaInclude.php` | by arrangement | Only for a store that has arranged the pull alternative to item 6: fetches the document itself (1 s timeout, 15 min file cache, last good copy) |

Keep the webhook secret and store id in environment variables or a config file outside the web
root; never in page HTML.

## Product page (item 6)

Mervia sends each product's document (structured data for `<head>`, the shopping guide for the
page) to `PUT /products/{id}/content` under the API key your store issued, and removes it with
`DELETE`. Keep it in a table and print it on the server:

```php
// once: a table with product_id, version, head_html, body_html, updated_at
$pdo->exec(MerviaProductContent::createTableSql());          // or your own DDL, same columns

$content = MerviaProductContent::withPdo($pdo);               // table mervia_product_content
// or, to keep it elsewhere: new MerviaProductContent($load, $save, $delete)  (see the class doc)
```
```php
// the endpoints, behind your Mervia API-key check (404 first when the product does not exist)
MerviaProductContent::respond($content->handlePut($id, file_get_contents('php://input')));   // PUT
MerviaProductContent::respond($content->handleDelete($id));                                   // DELETE
```
```php
<head> ... <?php $content->printHead($product['id']); ?> </head>
...
<?php $content->printBody($product['id']); ?>   <!-- where the shopping guide goes -->
```

`handlePut` answers `204` when the document is stored and also when it carried a `version`
lower than the stored one (ignored, as the contract allows); `422` in the contract's error shape
for a body that does not match the schema; `400` for a body that is not JSON. `handleDelete`
answers `204`, also when nothing was stored. The print helpers output the stored strings
unchanged, never throw, and print nothing when no document is stored, so the page renders as
before Mervia. One instance per request: head and body share one lookup.

### Pull alternative, by arrangement only

If you have agreed the pull option with Mervia (your store declares `content_pull` and fetches
the document from Mervia's include route with an include key), use `MerviaInclude` instead:

```php
$mervia = new MerviaInclude(getenv('MERVIA_INCLUDE_URL'), getenv('MERVIA_INCLUDE_KEY'), '/var/cache/mervia-include');
// <head> ... <?php $mervia->printHead($product['id']); ?> </head>   ...   <?php $mervia->printBody($product['id']); ?>
```

The cache directory must be writable by PHP and should survive deploys (it holds the last good
copy). One instance per request; `fetch($id)` never throws. After an error it serves the last
good copy for 60 s before trying again (`error_cache_seconds` option). Keep the include key out
of page HTML.

## Checkout: keep the cookie

```php
$order['mervia_attribution'] = MerviaAttributionCookie::forOrder();   // string or null; store as-is
```

It reads the `Cookie` header verbatim (no URL-decoding), so the value reaches Mervia exactly as
the tag wrote it.

## Orders (item 8)

Mervia reads `GET /orders` about once an hour. Give `MerviaOrders` a callback that returns your
**paid** orders as rows with the contract's keys, and let it answer the request:

```php
$orders = new MerviaOrders(function (?string $since, ?array $after, int $take) use ($pdo): array {
    // up to $take paid orders ordered by updated_at, id; updated_at >= $since when given;
    // strictly after $after (['updated_at' => ..., 'id' => ...]) when given
    $sql = 'SELECT id, number, status, paid_at, updated_at, currency, subtotal, shipping, tax, total,
                   refunded_total, mervia_attribution FROM orders WHERE paid_at IS NOT NULL';
    $args = array();
    if ($since !== null) { $sql .= ' AND updated_at >= ?'; $args[] = $since; }
    if ($after !== null) { $sql .= ' AND (updated_at, id) > (?, ?)'; $args[] = $after['updated_at']; $args[] = $after['id']; }
    $st = $pdo->prepare($sql . ' ORDER BY updated_at, id LIMIT ' . (int) $take);
    $st->execute($args);
    $rows = array();
    foreach ($st->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $row['line_items'] = loadLineItems($pdo, $row['id']);   // each: product_id, quantity, price (+ variant_id, sku)
        $rows[] = $row;                                        // timestamps as ISO 8601 with a timezone
    }
    return $rows;
});
MerviaOrders::respond($orders->handleList($_GET));   // behind your Mervia API-key check
```

Rules the callback keeps: only orders that have been paid are listed; `status` is `paid`,
`refunded` or `cancelled`; `updated_at` changes when the order is paid, refunded or cancelled;
`refunded_total` is the running total refunded so far (`"0.00"` until something is) and a
cancelled order is a full refund. `MerviaOrders` validates `limit` (1 to 250), `cursor` (one it
issued) and `updated_since` (ISO 8601 with a timezone), answers `422` in the contract's error
shape otherwise, asks the callback for one row more than the page to learn whether there is a
next page, and normalises each row with `MerviaOrderEvent::order()`, which refuses any key
containing `email`, `name`, `phone` or `address` and any email-shaped value.

## Webhooks, by arrangement only

By default no store sends webhooks: Mervia reads `GET /orders`. If you have arranged
`order_webhook` with Mervia, build and send the event (the same order object; `status` follows the
event, `refunded_total` is required on a refund):

```php
$payload = MerviaOrderEvent::build('order.paid', getenv('MERVIA_STORE_ID'), array(
    'id' => $order['id'],
    'number' => $order['number'],
    'paid_at' => $order['paid_at_iso'],             // ISO 8601 with timezone, or a DateTimeInterface
    'currency' => 'USD',
    'subtotal' => $order['subtotal'],
    'shipping' => $order['shipping'],
    'tax' => $order['tax'],
    'total' => $order['total'],
    'line_items' => $lineItems,                      // each: product_id, quantity, price (+ variant_id, sku)
    'mervia_attribution' => $order['mervia_attribution'],
    'customer_key' => MerviaOrderEvent::customerKey($order['email']),   // optional; never the email
));

$sender = new MerviaWebhookSender(getenv('MERVIA_WEBHOOK_URL'), getenv('MERVIA_WEBHOOK_SECRET'), '/var/spool/mervia');
$sender->enqueue($payload);   // fastest for checkout: cron sends it within a minute
// or: $sender->send($payload);  // try now (5 s timeout), spool on failure
```

`order.refunded` (with `refunded_total`) and `order.cancelled` take the same keys. Send
`order.paid` once per order: the first one fixes the amounts, and a later one for the same id
with different totals is treated as a duplicate. A change after payment goes out as
`order.refunded` with the new **cumulative** `refunded_total` (not the delta); `order.cancelled`
counts as a full refund. Mervia refuses a body over 256 KB. Unknown
order keys, any key containing `email`, `name`, `phone` or `address`, and email-shaped values
are refused with an `InvalidArgumentException`; put other non-personal fields in the fourth
`$extra` argument. Money is a decimal string (padded to two decimals; `"1.250"` stays exact) or
an int/float in whole units; timestamps need seconds and a timezone.
Product changes: `MerviaOrderEvent::product('product.updated', $storeId, $productId, $updatedAtIso)`.

Retry from cron every minute (overlapping runs are safe; a lock file guards the spool):

```php
// mervia-retry.php
require_once __DIR__ . '/mervia/mervia.php';
(new MerviaWebhookSender(getenv('MERVIA_WEBHOOK_URL'), getenv('MERVIA_WEBHOOK_SECRET'), '/var/spool/mervia'))->retryPending();
```
```
* * * * * php /path/to/mervia-retry.php
```

Retries wait 1, 2, 5, 10, 20, 30 min, 1, 2, 4, 6 and 8 h (12 attempts, about 22 h). An event
that never gets through, or an entry cron cannot read, moves to `/var/spool/mervia/failed/`
and one line naming the file goes to the PHP error log; the secret and the payload are never
logged. Spool files are named by a hash of the `event_id` and written 0660: run cron as the
web server's user or in its group.

## Tests

The tests use PHPUnit 9 on PHP 7.4 and run the helpers' real curl code against PHP's built-in
server (including the 1-second timeout). From `sdk/laravel/legacy-php74/`:

```bash
docker run --rm -v "$PWD":/app -w /app composer:2 composer install
docker run --rm -v "$PWD/../../..":/repo -w /repo/sdk/laravel/legacy-php74 php:7.4-cli vendor/bin/phpunit
```

`composer.json` here is dev-only (it pins the platform to PHP 7.4.30 so Composer picks PHPUnit 9);
the helpers themselves have no dependencies.
