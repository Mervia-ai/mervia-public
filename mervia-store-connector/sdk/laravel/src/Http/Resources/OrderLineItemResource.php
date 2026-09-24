<?php

namespace Mervia\StoreConnector\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;
use Mervia\StoreConnector\Support\Money;

/** One line of an order (item 8). price is the unit price. */
class OrderLineItemResource extends JsonResource
{
    public static $wrap = null;

    public function toArray(Request $request): array
    {
        return Shape::compact([
            'product_id' => (string) $this->product_id,       // the id GET /products lists
            'variant_id' => $this->variant_id === null ? null : (string) $this->variant_id,
            'sku' => $this->sku,
            'quantity' => (int) $this->quantity,
            'price' => Money::format($this->unit_price, 'price'),  // TODO: your unit price column
        ], ['variant_id']);
    }
}
