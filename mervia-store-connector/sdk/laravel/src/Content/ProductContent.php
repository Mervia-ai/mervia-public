<?php

namespace Mervia\StoreConnector\Content;

use Throwable;

/**
 * Item 6: the product-page document Mervia pushes to PUT /products/{id}/content.
 *
 *   store($id, $request->validated())   in your PUT handler: keeps the document, ignoring one
 *                                       whose version is lower than the stored one
 *   remove($id)                         in your DELETE handler (nothing stored is fine)
 *   head($id) / body($id)               in the product template, or the @merviaContentHead /
 *                                       @merviaContent directives: the stored strings, verbatim
 *
 * The strings are printed unchanged, rendered on the server. Reading never throws and prints
 * nothing when no document is stored, so the page renders as before Mervia.
 */
final class ProductContent
{
    /** @var array<string, array{version: int|null, head_html: string, body_html: string}> */
    private array $memo = [];

    public function __construct(private readonly ProductContentStore $store)
    {
    }

    /**
     * @param array{version: int|string, head_html?: string|null, body_html?: string|null} $document
     * @return bool true when stored; false when an older version was ignored
     */
    public function store(string|int $productId, array $document): bool
    {
        $id = (string) $productId;
        $version = (int) $document['version'];
        $current = $this->store->get($id);
        if ($current !== null && $version < $current['version']) {
            return false;
        }
        $this->store->put($id, $version, (string) ($document['head_html'] ?? ''), (string) ($document['body_html'] ?? ''));
        unset($this->memo[$id]);
        return true;
    }

    public function remove(string|int $productId): void
    {
        $this->store->delete((string) $productId);
        unset($this->memo[(string) $productId]);
    }

    /** @return array{version: int|null, head_html: string, body_html: string} Never throws. */
    public function fetch(string|int|null $productId): array
    {
        $empty = ['version' => null, 'head_html' => '', 'body_html' => ''];
        if ($productId === null || $productId === '') {
            return $empty;
        }
        $id = (string) $productId;
        try {
            return $this->memo[$id] ??= $this->store->get($id) ?? $empty;
        } catch (Throwable) {
            return $empty;
        }
    }

    public function head(string|int|null $productId): string
    {
        return $this->fetch($productId)['head_html'];
    }

    public function body(string|int|null $productId): string
    {
        return $this->fetch($productId)['body_html'];
    }
}
