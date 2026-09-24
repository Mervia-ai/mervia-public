# SDKs

One directory per platform. Each SDK is deliberately thin: the contract is what a store
implements, and the checker is what verifies it. An SDK only removes the non-obvious plumbing.

| Platform | Directory | Status |
| --- | --- | --- |
| Laravel (PHP) | [`laravel/`](laravel/) | first release |

What every SDK provides, in its platform's idiom:

1. **Orders list response** (item 8) — shapes the store's paid orders as `GET /orders` returns them: the order object of `contract/schemas/order.schema.json`, cursor pagination, `updated_since`, no customer personal data.
2. **Product-page content store and print** (item 6) — keeps the document Mervia sends to `PUT /products/{id}/content` (a lower `version` than the stored one may be ignored; `DELETE` removes it), and prints `head_html` and `body_html` verbatim, server-rendered.
3. **Attribution cookie read at checkout** (items 7, 8) — reads the `mervia_attr` cookie so its raw value can be stored on the order.
4. **Stubs for the endpoints the store serves** — request validation and response shapes for items 1, 2, 3, 4, 5, 6 and 8, generated or hand-written from `contract/openapi.yaml`.
5. **By arrangement with Mervia only:** a signed webhook sender (`order_webhook`, `product_webhook`: signs `timestamp.body`, retries with backoff for up to 24 hours) and an include helper for the pull alternative to item 6 (1-second timeout, 15-minute cache, last good copy on failure).

Adding a platform: copy the structure of `laravel/`, keep the item numbers, add tests, add a row above.
