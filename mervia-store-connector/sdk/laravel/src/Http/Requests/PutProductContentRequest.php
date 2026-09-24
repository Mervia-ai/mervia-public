<?php

namespace Mervia\StoreConnector\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

/**
 * PUT /products/{id}/content (item 6). Hand validated() to ProductContent::store(), which keeps
 * head_html and body_html unchanged and ignores a version lower than the stored one. Either part may be an empty string
 * (Laravel's ConvertEmptyStringsToNull turns that into null, hence nullable).
 */
class PutProductContentRequest extends FormRequest
{
    use RespondsWithContractErrors;

    public function rules(): array
    {
        return [
            'version' => ['required', 'integer', 'min:1'],
            'head_html' => ['present', 'nullable', 'string'],
            'body_html' => ['present', 'nullable', 'string'],
        ];
    }
}
