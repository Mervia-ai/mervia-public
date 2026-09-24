<?php

// Mervia Store Connector settings. Publish with:
//   php artisan vendor:publish --tag=mervia-config
// Every value comes from the environment; none of them belongs in page HTML.

return [

    // The store_id your GET /store endpoint returns (item 1). Sent in every webhook.
    'store_id' => env('MERVIA_STORE_ID'),

    // The key(s) YOUR store issued to Mervia, checked by the mervia.auth middleware on the
    // endpoints you serve (items 1, 2, 3, 4, 5, 6, 8). Two are accepted so a key can be
    // rotated without downtime: set the new one as the current key, keep the old one as
    // previous until Mervia confirms the switch, then clear previous. The helpers never use
    // these keys to call Mervia.
    'api_key_for_mervia' => env('MERVIA_API_KEY'),
    'api_key_for_mervia_previous' => env('MERVIA_API_KEY_PREVIOUS'),

    // Webhooks, by arrangement with Mervia only (order_webhook / product_webhook): where they
    // go and the shared secret that signs them. By default Mervia reads GET /orders instead.
    'webhook_url' => env('MERVIA_WEBHOOK_URL'),
    'webhook_secret' => env('MERVIA_WEBHOOK_SECRET'),
    'webhook_timeout_seconds' => (int) env('MERVIA_WEBHOOK_TIMEOUT_SECONDS', 10),

    // Item 6: the table that keeps the product-page document Mervia pushes to
    // PUT /products/{id}/content (see the package migration).
    'content_table' => env('MERVIA_CONTENT_TABLE', 'mervia_product_content'),

    // Item 6, pull alternative (by arrangement with Mervia only; leave unset otherwise): base
    // URL including your store key, e.g. https://app.mervia.ai/include/v1/{store_key}, and the
    // include key (server-side only).
    'include_url' => env('MERVIA_INCLUDE_URL'),
    'include_key' => env('MERVIA_INCLUDE_KEY'),
    'include_timeout_seconds' => (float) env('MERVIA_INCLUDE_TIMEOUT_SECONDS', 1),
    'include_cache_seconds' => (int) env('MERVIA_INCLUDE_CACHE_SECONDS', 900),
    // After an error or timeout the last good copy is served for this long before the next
    // attempt, so an outage costs one slow request per product per minute, not one per view.
    'include_error_cache_seconds' => (int) env('MERVIA_INCLUDE_ERROR_CACHE_SECONDS', 60),
    // Cache store to use (null = the default store).
    'include_cache_store' => env('MERVIA_INCLUDE_CACHE_STORE'),

    // Item 7: the store id the tracking tag carries.
    'tag_store_id' => env('MERVIA_TAG_STORE_ID'),

];
