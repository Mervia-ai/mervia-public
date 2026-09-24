# mervia-check

A conformance checker for the [Mervia Store Connector](../README.md) contract. Your engineering
team runs it against **your staging store** before the joint test with Mervia. It calls every
endpoint you implemented, reads your public pages the way a crawler does, and reports **pass**,
**fail** or **skip** for each contract item, with the exact request and response behind every
failure.

- **Staging only.** Items 5 and 6 create, publish, hide and delete a test article and a test
  product-page document. They run only with `--allow-writes`, and before the first write the
  checker prints a banner naming the host it is about to write to. Never point it at production.
- **It cleans up after itself.** Everything it writes carries the tag `mervia-conformance` and a
  run-unique title, and is removed at the end of the run, also when a check fails, when a request
  times out, on Ctrl-C and on SIGTERM. If removal itself fails, the report says so and names
  what to delete by hand.
- **It never prints secrets.** The API key, the probe key it sends to test 401s, the webhook
  secret, your include key and `--public-auth` credentials are replaced with `***` everywhere:
  report, JSON, error messages and progress output, including when your server echoes them
  back in a response body.

## Quick start

```sh
pip install ./checker            # Python 3.11+, or use Docker (below)

export MERVIA_CHECK_API_KEY=...  # keeps the key out of your shell history
mervia-check \
  --base-url https://staging.example.com/api/mervia/v1 \
  --store-id example-us \
  --allow-writes
```

The report goes to stdout; the exit code tells a CI job whether anything failed.

## What it checks

Items are numbered as in the integration document and the repository [README](../README.md).
By default the checker runs item 1, every item your `GET /store` declares in `capabilities`,
and items 7 and 9 (which have no capability; they read your public home page). An item you did
not declare is reported as `skip: not declared in capabilities`; an item you **named** in
`--items` but did not declare is a **fail** ("requested but not declared in capabilities").

Whatever `--items` says, the checker fails `1.store.https` for a base URL that is not https
(unless `--allow-http`) and `1.store.status` when `GET /store` does not answer 200, so a wrong
key never produces a green run.

| Item | Checks (result names) |
| --- | --- |
| 1 Store | `GET /store` answers 200 and matches the `Store` schema; `capabilities` holds only known values and not both `content_pull` and `content_push`; `store_id` equals `--store-id`; a random wrong key of the same length and a missing key answer 401 on `/store`, and a missing key answers 401 (not 404) on `GET /products`, `GET /orders`, `GET /articles` and `PATCH`/`DELETE` of a nonexistent article, for the capabilities you declare. |
| 2 Products | schema of `GET /products?limit=5`; at most 5 items; required fields; https URLs; `next_cursor` followed for up to 3 pages with no repeated id; a full first page with `next_cursor: null` is re-read with `limit=250` and fails if more products come back; `updated_since` far in the future returns nothing, and `updated_since=1970-01-01T00:00:00Z` returns products; `status=all` accepted; page 1 re-read gives the same ids; `GET /products/{id}` matches the list record on id, title and url; an unknown id answers 404; the first product's public page answers 200 without a key, with no redirect, and carries the title. |
| 3 Reviews | for `--product-id`, else a product with reviews, else the first: every page matches the schema; `summary.count` is at least the number of reviews returned; no `author_display_name` contains `@`. Reading zero reviews is a warning, since the checks then prove little. |
| 4 Pages | schema of `GET /pages`; every `kind` is a known kind. |
| 5 Articles | the full lifecycle, below. Needs `--allow-writes`. |
| 6 Content | `PUT`/`DELETE /products/{id}/content`, below; the pull alternative only when the store declares `content_pull`. Needs `--allow-writes`. |
| 7 Tracking tag | the home page carries `<script src="https://app.mervia.ai/tag/v1/mervia.js" data-store="...">` (attribute order and quoting do not matter; a tag inside an HTML comment does not count); `data-store` equals `--store-id`; the first product page carries it too. |
| 8 Orders | schema of `GET /orders?limit=5`; at most 5 items; required fields; only paid orders (`status` paid, refunded or cancelled, `paid_at` set); `refunded_total` between 0 and `total` (a cancelled order with less than a full refund is a warning); no customer name, email, phone or address (keys and email-shaped values); `next_cursor` followed for up to 3 pages with no repeated id (a full first page with `next_cursor: null` is re-read with `limit=250`); `updated_since` far in the future returns nothing, and `1970-01-01T00:00:00Z` returns orders. A store with no orders gets a warning: place and pay a test order on staging first. **By arrangement only**, for a store that declares `order_webhook`, with `--webhook-secret`: one order event arrives at the local receiver; `X-Mervia-Signature` is `sha256=` + hex HMAC-SHA256 of the `X-Mervia-Timestamp` value + `.` + the raw body (a signature over the body alone fails, and the message says so); `X-Mervia-Timestamp` is within 300 s; the body matches `order-event.schema.json`; `event_id` is present; `order.mervia_attribution` is present (null is fine); `store_id` matches. |
| 9 Search Console tag | `<meta name="google-site-verification" content="...">` on the home page. Absent is a **skip** ("not yet placed"), not a failure: Mervia sends you this tag later. |
| 11 Product webhook | by arrangement only, for a store that declares `product_webhook`: the same for a product event. See the receiver section for how long the checker waits for one. |

### Item 5, the article lifecycle

1. `POST /articles` a post tagged `mervia` and `mervia-conformance` → 201 or 200, `status`
   `hidden`, with `url`, `preview_url` and `content_digest`.
2. `GET /articles/{id}` matches; `GET /articles?tag=mervia-conformance&status=all` lists it, and
   every article that filter returns carries the tag (Mervia finds and cleans up its own posts
   with this filter).
3. The public `url`, fetched without a key, does **not** show it (401, 403, 404 or a redirect are
   all fine); it is not in `sitemap.xml` (a sitemap index is followed one level down).
4. `preview_url` fetched **with** the API key answers 200 and shows the title; fetched
   **without** it, it does not show the article.
5. `PATCH status=published` → `published`, `published_at` set, `content_digest` unchanged; the
   public URL now shows it; it appears in the sitemap (retried 3 times, 5 s apart).
6. `PATCH body_html` → `content_digest` changes.
7. `PATCH status=hidden` → the public URL stops showing it (retried for caches); it leaves the
   sitemap.
8. `DELETE` → 204 or 200; `GET` → 404.

Sitemaps are often cached, so the sitemap results are careful about what they claim. "Not in the
sitemap while hidden" only passes once the published article was later seen in the sitemap,
which shows the sitemap is fresh; otherwise it is a warning. No sitemap at all, a child sitemap
that cannot be read, or a published article that never appears are warnings too.

Whatever happens, the checker finally sweeps `GET /articles?tag=mervia-conformance&status=all`
for this run's title and slug (which also finds an article whose `POST` response was lost to a
timeout), hides and deletes what it finds, and confirms with a `GET` that answers 404.
`5.articles.cleanup` reports the outcome.

### Item 6 (`content_push`)

`PUT /products/{id}/content` with a document whose `head_html` is a
`<script type="application/ld+json" id="mervia-product-schema">` and whose `body_html` is a
`<section id="mervia-shopping-guide">`, both carrying a token unique to the run. The product's
public page, fetched as raw HTML without running JavaScript, must contain **both strings
exactly as sent** ("printed unchanged"; re-serialised JSON fails), the script inside `<head>`.
Then `DELETE`, and the ids must disappear (retried 3 times, 5 s apart, for caches). The document
is always deleted at the end. Its `version` is the current Unix time, so it is above any version
stored earlier.

If the chosen product's page already carries Mervia's ids, the checker leaves it alone (the
check would delete that document) and skips, unless you named the product with `--product-id`.

### Item 6, pull alternative (`content_pull`, by arrangement with Mervia) and the include stub

Only a store that has agreed the pull alternative with Mervia declares `content_pull`; the checks
below run only then. Under it your product template fetches Mervia's document from
`https://app.mervia.ai/include/v1/{store_key}/products/{product_id}`. For the check, the checker
plays that endpoint itself:

1. Start the checker with `--include-stub-listen 0.0.0.0:8787` (and `--allow-writes`). The stub
   starts before anything else and the checker prints its URL.
2. For the run, point your staging store's include base URL at the stub, e.g.
   `http://checker-host:8787/include/v1/`. The stub answers
   `/include/v1/<any store key>/products/<product id>` for the products under test, where the id
   must be the product's `id` from the products endpoint, not an internal id; it accepts any
   Bearer token.
3. **ok:** the checker fetches the first product's raw HTML. It must carry the stub's document
   verbatim, including this run's token. That proves the include is rendered on the server, and
   a copy cached before the run cannot pass. If the stub received no request at all, this fails
   and the phases below are skipped.
4. **slow:** the stub holds a **second** product, which the store has not fetched this run, for
   8 s. The page must still answer within 2.5 s, which a 1-second include timeout allows.
5. **error:** the stub answers 500 for the first product; the page must keep its last good copy.
   The contract lets you cache each product for 15 minutes, so a store that does not re-fetch
   here gets a **warning** ("the store did not call the include"), not a pass: the page answered
   from its cache and the phase proved nothing. Re-run after the cache has expired to see it pass.
6. **error_no_copy:** the stub answers 500 for a **third** product, one the store has not fetched
   this run and so has no last good copy for. The page must still render (without the document),
   and the stub must have been called. A cache cannot hide this phase: a store that fails or
   prints an error when the include fails is caught here.
7. **notfound:** the stub answers 404; the page must still render.
8. Every include request must use the path above and send a Bearer token, and that token must
   never appear in any page HTML the checker fetched. The token is used only for that
   comparison and for masking; it is never written to the report.

`--content-mode auto` (the default) tests whatever `capabilities` declares: `content_push`
normally, the pull checks only for a store that declares `content_pull`; `pull` or `push` forces one.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--base-url URL` | required | Your connector base URL, e.g. `https://staging.example.com/api/mervia/v1`. |
| `--api-key KEY` | required | The key you issued to Mervia. Also read from `MERVIA_CHECK_API_KEY`. A key with surrounding whitespace or a control character (a stray `\r`) is rejected without being echoed. |
| `--store-id ID` | | Expected `store_id`; compared with `GET /store`, the tag's `data-store` and webhook bodies. |
| `--items 1,2,5` | all | Which items to check. |
| `--allow-writes` | off | Run items 5 and 6, which write to the store. **Staging only.** Without it they are skipped. |
| `--public-base-url URL` | `https://<primary_host>` | Public origin of your storefront (see below). |
| `--public-auth USER:PASSWORD` | | HTTP basic auth for public pages, sitemaps and the keyless preview fetch. Also read from `MERVIA_CHECK_PUBLIC_AUTH`. Never printed. |
| `--product-id ID` | first listed | Product used for items 3 and 6. A product that does not exist is a failure. |
| `--webhook-secret S` | | Shared webhook secret; enables the by-arrangement webhook checks for a store that declares `order_webhook` or `product_webhook`. Also read from `MERVIA_CHECK_WEBHOOK_SECRET`. |
| `--webhook-listen HOST:PORT` | `0.0.0.0:8788` | Where the webhook receiver listens. |
| `--webhook-timeout SECONDS` | `300` | How long to wait for the webhook. |
| `--include-stub-listen HOST:PORT` | | Where the include stub listens; needed only for the pull alternative (`content_pull`). |
| `--content-mode auto\|pull\|push` | `auto` | Which item 6 delivery to test; `auto` follows the declared capability. |
| `--report text\|json` | `text` | Report format. |
| `--output FILE` | stdout | Write the report to a file; a one-line summary goes to stderr. |
| `--timeout SECONDS` | `10` | Per-request timeout. |
| `--insecure` | off | Skip TLS verification (self-signed staging certificates only). |
| `--allow-http` | off | Accept an `http://` base URL (local test stores only); otherwise `1.store.https` fails. |

The checker keeps under 2 requests per second, like Mervia, and honours `Retry-After` on a 429
(seconds or an HTTP date). Progress messages (where the receiver and stub listen, the write
banner, cleanup problems) go to stderr. The receiver and the stub bind before the first request;
if a port is taken the run stops with exit code 2.

### What "public base URL" means

The origin a shopper's browser uses for your storefront, such as `https://staging.example.com`.
The checker fetches `<public-base-url>/` for items 7 and 9 and `<public-base-url>/sitemap.xml`
for item 5. Without the option it uses `https://` plus `primary_host` from `GET /store`, and, for
the article sitemap, the origin of the article's own `url`. Pass it when your staging storefront
lives on a different host than `primary_host` says.

### Staging behind basic auth or an IP allowlist

Many staging sites are not public. If yours asks for HTTP basic auth, pass
`--public-auth USER:PASSWORD`; the checker sends it on every public-page request (never on API
requests, which carry the Bearer key). If yours only admits listed IP addresses, run the checker
from an allowed host, or add that host's address to the list for the run. A public page the
checker cannot fetch (401, 403, 429, 503, a network error) turns the product-page check into a
warning, but the tag, article and content checks need to see your pages and fail without them.

## The webhook receiver (by arrangement: `order_webhook`, `product_webhook`)

By default no store sends webhooks: Mervia reads orders from `GET /orders` and these checks do
not run. Only a store that has arranged webhooks with Mervia declares `order_webhook` or
`product_webhook`; for the check, it sends them to the checker instead of Mervia.

1. Run the checker on a host your **staging server can reach**, with `--webhook-secret` set to
   the secret your staging store signs with. The receiver starts before anything else, so an
   order placed while the other checks run is not lost.
2. Set your staging store's Mervia webhook URL to that host and `--webhook-listen` port, e.g.
   `http://checker-host:8788/`. If the checker runs on a laptop, expose the port with a tunnel
   (for example `cloudflared tunnel --url http://localhost:8788` or `ngrok http 8788`) and use the
   tunnel's URL.
3. Place a test order on staging (and edit a product, to test item 11). After the other checks,
   the checker waits up to `--webhook-timeout` seconds for the order event.

Item 11 is optional, so the checker waits the rest of the timeout for a product event only when
you name 11 in `--items`. Otherwise, once the order event is in, it reports a product event only
if one already arrived, and skips 11 if none did.

The receiver answers 200 to a correctly signed delivery (HMAC over `timestamp.body`) with a fresh timestamp and a JSON body,
401 to a bad signature or stale timestamp, 400 to a body that is not JSON, 413 to a body over
256 KB (Mervia's limit, applied before the signature is checked), and 411 to a body with
neither `Content-Length` nor chunked transfer encoding. It runs only for the length of the check.

## Docker

The image is built locally until one is published:

```sh
docker build -t mervia-check checker/

docker run --rm --init -e MERVIA_CHECK_API_KEY mervia-check \
  --base-url https://staging.example.com/api/mervia/v1 --store-id example-us --allow-writes

# with the webhook receiver published on the host (and the include stub, pull alternative only)
docker run --rm --init -p 8788:8788 -p 8787:8787 \
  -e MERVIA_CHECK_API_KEY -e MERVIA_CHECK_WEBHOOK_SECRET \
  mervia-check --base-url https://staging.example.com/api/mervia/v1 --store-id example-us \
  --allow-writes --include-stub-listen 0.0.0.0:8787 --report json
```

Use `--init` so `docker stop` (SIGTERM) reaches the checker, which then cleans up before it
exits. A staging site running on your own machine is `host.docker.internal` from inside the
container, not `localhost`: for example
`--base-url https://host.docker.internal:8443/api/mervia/v1 --public-base-url https://host.docker.internal:8443`
(on Linux, add `--add-host=host.docker.internal:host-gateway`). A self-signed certificate there
also needs `--insecure`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | No check failed (passes, warnings and skips only). |
| 1 | At least one check failed. |
| 2 | Usage error, a rejected key or secret, a port that could not be bound, or the base URL could not be reached at all. |
| 130 | Interrupted (Ctrl-C or SIGTERM); cleanup was attempted and its messages are on stderr. |

## Reading the report

Each line is `PASS`, `WARN`, `FAIL` or `SKIP` with a stable result name such as
`2.products.pagination`. A `WARN` counts as a pass: the checker could not prove the point from
where it runs (your public page blocked the request, your sitemap looked cached), so check it by
hand. Every `FAIL` shows the request the checker sent and the response it received.

The report ends with two lines. `RESULT:` is `FAIL` if any check failed. `GO-LIVE:` says whether
the go-live items 1, 2, 3, 5, 6, 7 and 8 were all checked in this run, e.g.
`GO-LIVE: INCOMPLETE (5, 6 not checked)` when you ran without `--allow-writes`. `--report json` carries the same as `summary` and `go_live`.

## What a green report means

A run with exit code 0 and `GO-LIVE: COMPLETE` means your staging implementation answers every
declared endpoint in the shapes the contract describes, rejects a missing or wrong key, hides and
publishes articles the way Mervia relies on, renders the product-page document on the server,
carries the tracking tag, and signs a real order webhook correctly. It does not prove that
production is configured the same way, that your data is complete or accurate, or that the parts
you skipped work: items you did not declare, a webhook you did not trigger, and warnings you did
not check by hand are outside what it saw. It is the entry ticket for the joint test with Mervia,
not a replacement for it.

## Development

```sh
cd checker
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q          # no network: an in-process fake store plus local servers
.venv/bin/ruff check .
```

`tests/fakestore.py` implements the contract well enough for every check to pass, and names one
deliberate defect (`breaks=...`) per check so the tests prove each one is caught.

The package carries a copy of `../contract/` under `src/mervia_check/contract/` so an installed
checker needs no checkout. After changing the contract, refresh the copy with
`make sync-contract` (or `python3 scripts/sync_contract.py`); `tests/test_contract.py` fails while
the two differ.

### Smoke run over the network

The unit tests never open a socket. To see the installed command, or the Docker image, run the
whole way through against a real server, serve the test fake store over HTTPS with a self-signed
certificate and point the checker at it:

```sh
# shell 1: the fake store, delivering a signed order and product event to the receiver after 10 s
.venv/bin/python scripts/serve_fakestore.py --listen 0.0.0.0:8443 --public-host localhost \
  --webhook-to http://127.0.0.1:8788/ --webhook-secret whsec-test

# shell 2: the checker (expected: RESULT: PASS, exit 0, GO-LIVE: COMPLETE)
MERVIA_CHECK_API_KEY=test-key-123 .venv/bin/mervia-check \
  --base-url https://localhost:8443/api/mervia/v1 --public-base-url https://localhost:8443 \
  --store-id example-us --allow-writes --insecure --webhook-secret whsec-test \
  --items 1,2,3,4,5,6,7,8,9,11
```

The store declares the by-arrangement webhooks only with `--webhooks` (implied by `--webhook-to`), so
the run above also exercises the receiver; without them item 8 is the `GET /orders` checks alone.

`--content pull --include-url http://127.0.0.1:8797/include/v1/` on the store plus
`--include-stub-listen 127.0.0.1:8797` on the checker exercises the pull alternative instead ( add `--include-cache` on the store to see `6.pull.error` warn as it does against a store with the contract's 15-minute cache).
For the Docker image, serve with `--public-host host.docker.internal` and run the container with
`-p 8788:8788 -p 8797:8787 --include-stub-listen 0.0.0.0:8787` and
`--base-url https://host.docker.internal:8443/api/mervia/v1`. `--breaks no_tag,review_email` on the
store switches on named defects from `tests/fakestore.py`, so the run must exit 1 and name them.
