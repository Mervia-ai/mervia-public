# Controllers: the endpoints your store serves

This package does not ship controllers: your models, columns and URLs are your own. It ships
the pieces around them — the `mervia.auth` middleware, FormRequests for the three write bodies,
and JsonResource stubs for every shape. `contract/openapi.yaml` is the authority; this is the
short version.

## Routes

```php
// routes/api.php  (the prefix is yours to choose; tell Mervia the base URL)
use Mervia\StoreConnector\Http\Requests\{CreateArticleRequest, UpdateArticleRequest, PutProductContentRequest};

Route::prefix('mervia/v1')->middleware(['mervia.auth', 'throttle:120,1'])->group(function () {
    Route::get('/store', [MerviaController::class, 'store']);                       // item 1
    Route::get('/products', [MerviaController::class, 'products']);                 // item 2
    Route::get('/products/{id}', [MerviaController::class, 'product']);             // item 2
    Route::get('/products/{id}/reviews', [MerviaController::class, 'reviews']);     // item 3
    Route::get('/orders', [MerviaController::class, 'orders']);                     // item 8
    Route::get('/pages', [MerviaController::class, 'pages']);                       // item 4, optional
    Route::get('/articles', [MerviaController::class, 'articles']);                 // item 5
    Route::post('/articles', [MerviaController::class, 'createArticle']);           // item 5
    Route::get('/articles/{id}', [MerviaController::class, 'article']);             // item 5
    Route::patch('/articles/{id}', [MerviaController::class, 'updateArticle']);     // item 5
    Route::delete('/articles/{id}', [MerviaController::class, 'deleteArticle']);    // item 5
    Route::put('/products/{id}/content', [MerviaController::class, 'putContent']);  // item 6
    Route::delete('/products/{id}/content', [MerviaController::class, 'deleteContent']);
});
```

## Rules that are easy to miss

- **Auth.** `mervia.auth` accepts `Authorization: Bearer <key>` for `MERVIA_API_KEY` or
  `MERVIA_API_KEY_PREVIOUS` (constant-time compare) and answers anything else with
  `401 {"error":"unauthorized"}`. To rotate: put the new key in `MERVIA_API_KEY`, the old one in
  `MERVIA_API_KEY_PREVIOUS`, give Mervia the new key, then clear the previous one.
- **Errors** are `{"error": "<code>", "message": "<text>"}`. The FormRequests already answer
  `422 {"error":"invalid", ...}`. Return `404 {"error":"not_found"}` for unknown ids. Mervia
  honours `429` with `Retry-After`.
- **Lists** take `limit` (at most 250; 100 for reviews), `cursor` and `updated_since`, and answer
  `{"items": [...], "next_cursor": "..."|null}`. Laravel's `cursorPaginate()` gives you an opaque
  cursor; return `next_cursor` as `$page->nextCursor()?->encode()`.
- **`GET /products?status=all`** must include drafts and archived products, so Mervia notices removals.
- **`GET /orders`** (item 8; declare `orders`) lists only orders that have been **paid**, as
  `OrderResource` shapes them, ordered by `updated_at`, and honours `updated_since`: Mervia
  reads about once an hour with it set to its last read. `updated_at` must change when the order
  is paid, refunded or cancelled. `refunded_total` is the running total refunded so far
  (`"0.00"` until something is), and a cancelled order counts as a full refund. Mervia keeps the
  amounts from the first time it reads the order as paid. Never return a customer name, email,
  phone or address. Something like:

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
- **Hidden articles.** `POST /articles` always creates `status: hidden`. A hidden article is
  not reachable at its public URL (404 to everyone), not in your blog listing, not in your
  sitemap, not in feeds. Scope every public query with something like
  `->where('status', 'published')`. `GET /articles` for Mervia *does* include hidden ones, and
  filters by `tag`, `type` and `status` when given.
- **`preview_url`** renders a hidden article only to a request carrying Mervia's key. Put the
  preview route behind `mervia.auth` too, and send `X-Robots-Tag: noindex`.
- **`content_digest`** is a hash of the stored `body_html` and nothing else
  (`ArticleResource` does `sha256:<hex>`), so it changes only when the body changes.
- **`featured_image_url`**: copy the image into your own storage, or answer `415`; Mervia then
  publishes without it.
- **`PATCH status: published`** puts the article at its URL, in the listing and in the sitemap;
  `status: hidden` takes it out of all three. `DELETE` answers `204`.
- **`PUT /products/{id}/content`** (item 6; declare `content_push`): store `head_html` and
  `body_html` unchanged, ignore a lower `version` than the stored one, render them on the server.
  `DELETE` removes the document; `204` or `404` when nothing is stored both count as removed.
  The package does this for you:

  ```php
  public function putContent(PutProductContentRequest $request, string $id, ProductContent $content)
  {
      abort_unless(Product::whereKey($id)->exists(), 404, 'not_found');
      $content->store($id, $request->validated());   // false = an older version, ignored
      return response()->noContent();
  }

  public function deleteContent(string $id, ProductContent $content)
  {
      $content->remove($id);
      return response()->noContent();
  }
  ```

  Then `@merviaContentHead($product->id)` inside `<head>` and `@merviaContent($product->id)` where
  the guide goes print the stored strings verbatim (see the package README).
