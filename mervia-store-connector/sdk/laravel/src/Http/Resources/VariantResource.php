<?php

namespace Mervia\StoreConnector\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;
use Mervia\StoreConnector\Support\Money;

/** One variant inside a product (item 2). Money is a decimal string plus an ISO 4217 code. */
class VariantResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        return Shape::compact([
            'id' => (string) $this->id,
            'title' => $this->title,
            'sku' => $this->sku,
            'gtin' => $this->barcode,                            // TODO: UPC/EAN column, if any
            'options' => $this->options ?? (object) [],          // e.g. {"Plug": "US"}
            'price' => Money::format($this->price),              // TODO: if you store cents, divide by 100 first
            'compare_at_price' => $this->compare_at_price === null ? null : Money::format($this->compare_at_price),
            'currency' => $this->currency ?? 'USD',              // TODO: your currency
            'available' => (bool) $this->available,             // TODO: in stock and purchasable
            'inventory_quantity' => $this->stock,
        ], ['compare_at_price']);
    }
}
