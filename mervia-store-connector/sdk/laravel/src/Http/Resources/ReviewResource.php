<?php

namespace Mervia\StoreConnector\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;

/**
 * One review (item 3). Return only reviews already shown publicly on the site.
 * author_display_name is what the site displays (a first name, initials) — never an email.
 */
class ReviewResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        return Shape::compact([
            'id' => (string) $this->id,
            'rating' => (int) $this->rating,
            'title' => $this->title,
            'body' => (string) $this->body,
            'author_display_name' => $this->display_name,   // TODO: the name as displayed
            'verified_buyer' => (bool) $this->verified,
            'created_at' => Shape::time($this->created_at),
        ]);
    }
}
