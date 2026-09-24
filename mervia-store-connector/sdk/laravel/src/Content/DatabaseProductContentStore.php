<?php

namespace Mervia\StoreConnector\Content;

use Illuminate\Database\Query\Builder;
use Illuminate\Support\Facades\DB;

/**
 * Keeps the documents in the `mervia_product_content` table (name: config mervia.content_table;
 * migration: `php artisan vendor:publish --tag=mervia-migrations`, or let the package's
 * migration run). One row per product: product_id, version, head_html, body_html, updated_at.
 */
final class DatabaseProductContentStore implements ProductContentStore
{
    public function __construct(private readonly ?string $table = null, private readonly ?string $connection = null)
    {
    }

    public function get(string $productId): ?array
    {
        $row = $this->query()->where('product_id', $productId)->first();
        if ($row === null) {
            return null;
        }
        return [
            'version' => (int) $row->version,
            'head_html' => (string) $row->head_html,
            'body_html' => (string) $row->body_html,
        ];
    }

    public function put(string $productId, int $version, string $headHtml, string $bodyHtml): void
    {
        $this->query()->updateOrInsert(
            ['product_id' => $productId],
            ['version' => $version, 'head_html' => $headHtml, 'body_html' => $bodyHtml, 'updated_at' => now()],
        );
    }

    public function delete(string $productId): void
    {
        $this->query()->where('product_id', $productId)->delete();
    }

    private function query(): Builder
    {
        $table = $this->table ?? (string) config('mervia.content_table', 'mervia_product_content');
        return DB::connection($this->connection)->table($table);
    }
}
