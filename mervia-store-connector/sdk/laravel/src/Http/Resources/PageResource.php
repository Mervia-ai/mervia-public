<?php

namespace Mervia\StoreConnector\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;

/** One policy or information page (item 4, optional). */
class PageResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        return [
            'id' => (string) $this->id,
            // TODO: one of page, shipping, returns, warranty, privacy, terms, faq, about, contact
            'kind' => $this->kind ?? 'page',
            'title' => $this->title,
            'url' => url('/pages/' . $this->slug),          // TODO: the page's public URL
            'body_html' => (string) $this->body,
            'updated_at' => Shape::time($this->updated_at),
        ];
    }
}
