# Contract

The contract as code. Where the integration document's prose and these files disagree, these
files win.

| File | Covers |
| --- | --- |
| `openapi.yaml` | Every endpoint the store serves: items 1 (store), 2 (products), 3 (reviews), 4 (pages), 5 (articles) and 6 (`PUT`/`DELETE /products/{id}/content`, the product-page document Mervia pushes). |
| `schemas/order.schema.json` | Item 8, the order object `GET /orders` lists. Defined once; the by-arrangement order webhook carries the same object. |
| `schemas/order-event.schema.json` | By arrangement with Mervia only: the order webhook a store may send instead of being read. |
| `schemas/product-event.schema.json` | By arrangement with Mervia only: the product-changed webhook (item 11). |
| `schemas/include-response.schema.json` | The pull alternative to item 6, available by arrangement with Mervia only: what Mervia returns to a store that fetches the document itself. |

## Orders and amounts (item 8)

`GET /orders` lists only orders that have been **paid**; an order never paid is not listed at
all. Orders come oldest change first (ascending `updated_at`); an unsorted listing is refused
and the store is marked failed. Mervia's first read after connecting goes back 60 days; after
that it reads about once an hour with `updated_since` set to its last read, so `updated_at`
must change whenever the order is paid, refunded or cancelled. Mervia keeps an
order's amounts from the first time it reads the order as paid: a change of amount after
payment is recorded as a refund raising `refunded_total`, which is the running total refunded
so far (`"0.00"` until something is), not a delta; a cancelled order counts as a full refund
(`refunded_total` equal to `total`). No customer name, email, phone or address is returned;
`customer_key` (a SHA-256 of the lowercase email) is optional. The order object is
`schemas/order.schema.json`.

## Webhooks (by arrangement with Mervia only)

By default no store sends webhooks: Mervia reads orders from `GET /orders` and re-reads changed
products on its own schedule. Only by arrangement with Mervia does a store declare
`order_webhook` or `product_webhook` and send signed events (`schemas/order-event.schema.json`,
`schemas/product-event.schema.json`). When arranged, every webhook carries two headers:

```
X-Mervia-Timestamp: <unix seconds at send time>
X-Mervia-Signature: sha256=<lowercase hex HMAC-SHA256, keyed with the shared secret, of: timestamp + "." + raw request body>
```

The HMAC input is the timestamp header's exact value, then a single `.`, then the raw request
body, as bytes (`HMAC-SHA256(secret, "1700000000." + body)`). Sign the exact bytes you send;
re-encoding the body after signing breaks the signature. Mervia rejects the event when the
signature does not verify or the timestamp is more than 300 seconds from its own clock, in
either direction, and ignores a repeated `event_id`. Signing the timestamp is what makes the
5-minute window real: a captured delivery cannot be resent later with a fresh timestamp. A body
larger than 256 KB (262,144 bytes) is refused before the signature is checked. Mervia answers
`2xx` on accept; on any other status the store retries with exponential backoff for up to
24 hours, re-signing each attempt with a fresh timestamp. The order webhook carries the same
order object as `GET /orders`, amount rules included. The `laravel/` helpers implement this; the
checker's local receiver verifies it and names a body-only signature when it sees one.

## Generating stubs

`openapi.yaml` is OpenAPI 3.1. Any standard generator works for Laravel request validation and
API Resource stubs; the `laravel/` directory carries hand-written stubs for the same shapes.

## Rules the schemas cannot express

Stated in `openapi.yaml`'s descriptions and enforced by Mervia (and, where marked, by the checker):

- **Base URL** on `primary_host`'s domain (the primary host without a leading `www.`, or a name
  under it); https only; no IP address, no `*.myshopify.com` host. Accepting two valid API keys
  at once lets either party rotate; 401 and 403 both mean a rejected key.
- **Responses Mervia accepts:** at most 10 MB; `Accept-Encoding: identity`, a compressed body is
  refused; 30 seconds per request; redirects are not followed on any endpoint. Mervia sends at
  most 2 requests per second, reads the full catalog at most every 6 hours, and honours 429
  with `Retry-After`.
- **Capabilities → items:** `products` 2, `reviews` 3, `pages` 4, `articles` 5, `content_push` 6,
  `orders` 8. Items 7 and 9 have no value; Mervia reads them from the public home page.
- **`store_id`:** stable forever, not all digits, not starting with `custom:`, and equal to the
  tracking tag's `data-store` (checker: `1.store.store_id`, `7.tag.store_id`).
- **`hosts`:** every declared host on `primary_host`'s domain; no IP addresses, no
  `*.myshopify.com`. **Product URLs** are https, final (no redirect) and on a declared host;
  **image URLs** are https with no whitespace and none of `( ) < > " '` or a backtick
  (percent-encode them). Mervia refuses any other product or image URL.
- **Products:** a product missing from one full listing is marked inactive and returns when it
  reappears, so a full listing includes every active product. `specs`, `category` and `rating`
  matter most; ids are stable across edits (an auto-increment id is, a slug is not).
- **Reviews:** only reviews already shown on the site; `author_display_name` never an email;
  `summary.count` at least the number returned (checker: `3.reviews.*`).
- **Articles:** the preview and the public page show the body text as sent, with nothing rewritten
  (no smart quotes) or inserted inside the body; `preview_url` must not show the article without
  the key; `type: page` is optional and not needed for go-live (checker: `5.articles.*`).
- **Product-page content:** `head_html` holds `application/ld+json` blocks with the ids
  `mervia-product-schema`, `mervia-faq-schema`, `mervia-review-schema`; `body_html` a
  `<section id="mervia-shopping-guide">`; both printed unchanged and server-rendered. Mervia
  looks for these ids on the public page after every change (checker: `6.push.*`).
- **Orders:** listed oldest change first (ascending `updated_at`); an unsorted listing is refused
  and the store is marked failed. The first read after connecting goes back 60 days, then
  Mervia reads hourly (checker: `8.orders.*`).

## Validating a change

`checker/` contains `tests/test_contract.py`, which loads these files, checks they parse, and
checks the examples in `openapi.yaml` against their schemas. Run it with `pytest` from
`checker/`.
