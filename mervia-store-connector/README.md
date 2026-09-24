# Mervia Store Connector

The contract, conformance checker and Laravel helpers for connecting a store that is not on
Shopify to [Mervia](https://mervia.ai)'s marketing agent.

Mervia normally connects to a store through its Shopify app. A store on its own platform
connects through a small set of HTTP endpoints the store's team provides, plus two snippets in
its page templates. This repository holds everything a store's engineering team needs to build
and verify that integration:

| Directory | What it is |
| --- | --- |
| [`contract/`](contract/) | The contract as code: `openapi.yaml` for the endpoints the store serves, and JSON Schemas for the order object `GET /orders` lists and, by arrangement only, the two webhooks and the include document. Where prose and these files disagree, the files win. |
| [`checker/`](checker/) | `mervia-check`, a command-line conformance checker. Point it at a staging base URL and API key and it reports pass or fail per item, with the failing request and response. Staging only; it tags and removes everything it creates. |
| [`sdk/`](sdk/) | One SDK per platform, each a thin set of helpers for the parts the store's code has to get right (the orders list response, storing and printing the product-page document, the attribution cookie; the signed webhook sender only by arrangement) plus stubs for the endpoints the store serves. Today: [`sdk/laravel/`](sdk/laravel/), with PHPUnit tests. Other platforms are added as siblings; the contract and the checker do not change per platform. |

## The integration in one picture

```
store (e.g. Laravel)                          Mervia
--------------------                          ------
GET  /store, /products, /products/{id},   <-- reads catalog, reviews, pages
     /products/{id}/reviews, /pages
GET  /orders                              <-- reads paid orders hourly and attributes them
POST/PATCH/DELETE /articles               <-- writes blog posts (create hidden, publish, revert)
PUT/DELETE /products/{id}/content         <-- Mervia pushes the product-page document
                                              (guide + structured data); the store prints it
every page  --tracking tag-->             Mervia counts AI-referred sessions
```

## Item numbers

Every check, schema and helper refers to the same eleven items as the integration document a
store receives from Mervia:

| # | Item | Group |
| --- | --- | --- |
| 1 | Store identity endpoint `GET /store` | Read |
| 2 | Products endpoint `GET /products`, `GET /products/{id}` | Read |
| 3 | Reviews endpoint `GET /products/{id}/reviews` | Read |
| 4 | Pages endpoint `GET /pages` (optional) | Read |
| 5 | Articles API `/articles` | Publish |
| 6 | Product-page content `PUT/DELETE /products/{id}/content` | Publish |
| 7 | Tracking tag | Measure |
| 8 | Orders endpoint `GET /orders` | Measure |
| 9 | Search Console tag | Measure |
| 10 | Chat widget tag (later) | Later |
| 11 | Product-changed webhook (by arrangement only) | Measure |

Go-live needs items 1, 2, 3, 5, 6, 7 and 8. Item 4 (pages) is optional, item 9 is placed once Mervia
sends the tag, and item 10 comes later.

The tracking tag (item 7) records the page path and referrer, nothing typed by the shopper, and
removes path segments that look like secrets (a password-reset token, for example) before
anything is stored.

## Quick start

```
# run the checker against a staging store (from this directory)
docker build -t mervia-check checker/
docker run --rm --init mervia-check \
  --base-url https://staging.example.com/api/mervia/v1 \
  --api-key "$MERVIA_TEST_KEY" \
  --store-id example-us \
  --allow-writes   # only against a STAGING store; items 5 and 6 create and remove content
```

See [`checker/README.md`](checker/README.md) for every option, including the local webhook
receiver.

The store never has to call Mervia. Mervia reads and writes four groups of endpoints with the
store's own API key: store and catalog (items 1, 2, 3, 4), orders (item 8, `GET /orders`, read
about once an hour), articles (item 5) and product-page content (item 6, pushed to
`PUT /products/{id}/content`). So the store needs no second credential, sends no webhooks and
makes no render-time call to Mervia. Three things exist by arrangement with Mervia only, and
the contract, the checker and the SDKs keep them working: the order and product webhooks
(`order_webhook`, `product_webhook`) and the pull alternative to item 6 (`content_pull`).

## Layout for new platforms

The contract is platform-neutral and the checker tests any implementation of it. A new platform
adds a directory under `sdk/` (for example `sdk/woocommerce/` or `sdk/nextjs/`) carrying the same
three helpers and the stubs, in that platform's language, with its own tests and its own README.
Nothing else in the repository changes.

## Versioning

The contract is versioned by the `info.version` field of `contract/openapi.yaml`. A change that
requires a store to change its implementation bumps the major version and is announced.
Unknown fields are ignored on both sides, so a store may add fields at any time.

## License

MIT. See [LICENSE](LICENSE).
