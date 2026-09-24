<?php

namespace Mervia\StoreConnector\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

/** PATCH /articles/{id} (item 5). status "published" sets it live; "hidden" takes it down. */
class UpdateArticleRequest extends FormRequest
{
    use RespondsWithContractErrors;

    public function rules(): array
    {
        return [
            'title' => ['sometimes', 'string'],
            'slug' => ['sometimes', 'string', 'max:255'],
            'excerpt' => ['sometimes', 'nullable', 'string'],
            'body_html' => ['sometimes', 'string'],
            'author' => ['sometimes', 'nullable', 'string'],
            'tags' => ['sometimes', 'array'],
            'tags.*' => ['string'],
            'featured_image_url' => ['sometimes', 'nullable', 'url', 'starts_with:https://'],
            'meta_title' => ['sometimes', 'nullable', 'string'],
            'meta_description' => ['sometimes', 'nullable', 'string'],
            'status' => ['sometimes', 'in:hidden,published'],
        ];
    }
}
