<?php

namespace Mervia\StoreConnector\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;

/**
 * One product (item 2). A stub: replace each TODO with your own columns and relations.
 * Eager-load images and variants in the controller to avoid N+1 queries.
 * A product without variants must still send one variant carrying the product's own price.
 */
class ProductResource extends JsonResource
{
    public static $wrap = null;

    public function toArray(Request $request): array
    {
        return Shape::compact([
            'id' => (string) $this->id,
            'handle' => $this->slug,                       // TODO: your slug column
            'url' => url('/products/' . $this->slug),      // TODO: the final canonical URL, never one that redirects
            'title' => $this->name,                        // TODO: your title column
            'description_html' => (string) $this->description,
            'brand' => $this->brand,
            'product_type' => $this->type,
            'tags' => $this->tags ?? [],
            'status' => $this->status,                     // TODO: map to active | draft | archived
            'published_at' => Shape::time($this->published_at),
            'created_at' => Shape::time($this->created_at),
            'updated_at' => Shape::time($this->updated_at),
            'images' => $this->images->values()->map(fn ($image, $i) => Shape::compact([   // TODO: your images relation
                'url' => $image->url,                      // absolute https URL
                'alt' => $image->alt,
                'position' => $i + 1,
            ]))->all(),
            'variants' => VariantResource::collection($this->variants)->resolve($request),
            // Optional: 'options', 'specs' [{name, value}], 'category', and 'rating' {average, count}.
        ], ['published_at']);
    }
}
