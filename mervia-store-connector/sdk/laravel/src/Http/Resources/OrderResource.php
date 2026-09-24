<?php

namespace Mervia\StoreConnector\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;
use Mervia\StoreConnector\Support\Money;
use Mervia\StoreConnector\Webhook\OrderEvent;

/**
 * One paid order for GET /orders (item 8; contract/schemas/order.schema.json). A stub: replace
 * each TODO with your own columns. List only orders that have been paid, ordered by updated_at,
 * and honour updated_since: Mervia reads with it set to its last read. refunded_total is the
 * running total refunded so far ("0.00" while nothing is); a cancelled order is a full refund.
 * Never return a customer name, email, phone or address; customer_key is the hash, optional.
 */
class OrderResource extends JsonResource
{
    public static $wrap = null;

    public function toArray(Request $request): array
    {
        return Shape::compact([
            'id' => (string) $this->id,
            'number' => $this->number,                                  // TODO: the number the customer sees
            'status' => $this->status,                                  // TODO: map to paid | refunded | cancelled
            'paid_at' => Shape::time($this->paid_at),
            'updated_at' => Shape::time($this->updated_at),             // must change on pay, refund, cancel
            'currency' => $this->currency,
            'subtotal' => Shape::money($this->subtotal),
            'discount_total' => Shape::money($this->discount_total),
            'shipping' => Shape::money($this->shipping_total),          // TODO: your column names
            'tax' => Shape::money($this->tax_total),
            'total' => Money::format($this->total, 'total'),            // what the customer paid
            'refunded_total' => Money::format($this->refunded_total ?? 0, 'refunded_total'),
            'line_items' => OrderLineItemResource::collection($this->items)->resolve($request),  // TODO: your items relation
            'mervia_attribution' => $this->mervia_attribution,          // stored at checkout; null when absent
            'customer_key' => $this->email ? OrderEvent::customerKey($this->email) : null,     // optional; never the email
        ], ['mervia_attribution']);
    }
}
