<?php

namespace Mervia\StoreConnector\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

/** POST /articles (item 5). The article is always created hidden. */
class CreateArticleRequest extends FormRequest
{
    use RespondsWithContractErrors;

    public function rules(): array
    {
        return [
            'type' => ['required', 'in:post,page'],
            'title' => ['required', 'string'],
            'slug' => ['sometimes', 'nullable', 'string', 'max:255'],
            'excerpt' => ['sometimes', 'nullable', 'string'],
            'body_html' => ['required', 'string'],
            'author' => ['sometimes', 'nullable', 'string'],
            'tags' => ['sometimes', 'array'],
            'tags.*' => ['string'],
            // If you cannot copy a remote image into your media storage, answer 415 instead.
            'featured_image_url' => ['sometimes', 'nullable', 'url', 'starts_with:https://'],
            'meta_title' => ['sometimes', 'nullable', 'string'],
            'meta_description' => ['sometimes', 'nullable', 'string'],
            'status' => ['sometimes', 'in:hidden'],
        ];
    }
}
