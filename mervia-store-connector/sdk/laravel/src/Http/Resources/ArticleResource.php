<?php

namespace Mervia\StoreConnector\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;

/**
 * One article (item 5), hidden or published.
 * content_digest must change only when body_html changes: hash the stored body, nothing else.
 */
class ArticleResource extends JsonResource
{
    public static $wrap = null;

    public function toArray(Request $request): array
    {
        return Shape::compact([
            'id' => (string) $this->id,
            'type' => $this->type,                                  // post | page
            'title' => $this->title,
            'slug' => $this->slug,
            'url' => url('/blog/' . $this->slug),                   // TODO: the final public URL
            'preview_url' => url('/blog/preview/' . $this->id),     // TODO: renders hidden articles to Mervia's key only
            'excerpt' => $this->excerpt,
            'body_html' => (string) $this->body_html,
            'author' => $this->author,
            'tags' => $this->tags ?? [],
            'featured_image_url' => $this->featured_image_url,
            'meta_title' => $this->meta_title,
            'meta_description' => $this->meta_description,
            'status' => $this->status,                              // hidden | published
            'published_at' => Shape::time($this->published_at),
            'created_at' => Shape::time($this->created_at),
            'updated_at' => Shape::time($this->updated_at),
            'content_digest' => 'sha256:' . hash('sha256', (string) $this->body_html),
        ], ['featured_image_url', 'published_at']);
    }
}
