<?php

namespace Mervia\StoreConnector\Content;

/**
 * Where the product-page documents Mervia pushes (item 6) are kept. The package binds
 * DatabaseProductContentStore; bind your own implementation to keep them elsewhere.
 */
interface ProductContentStore
{
    /** @return array{version: int, head_html: string, body_html: string}|null */
    public function get(string $productId): ?array;

    public function put(string $productId, int $version, string $headHtml, string $bodyHtml): void;

    public function delete(string $productId): void;
}
