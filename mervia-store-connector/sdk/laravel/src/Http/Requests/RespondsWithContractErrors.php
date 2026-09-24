<?php

namespace Mervia\StoreConnector\Http\Requests;

use Illuminate\Contracts\Validation\Validator;
use Illuminate\Http\Exceptions\HttpResponseException;

/** Validation failures answer 422 in the contract's error shape: {"error": "invalid", "message": ...}. */
trait RespondsWithContractErrors
{
    public function authorize(): bool
    {
        return true; // Authentication is the mervia.auth middleware's job.
    }

    protected function failedValidation(Validator $validator): void
    {
        throw new HttpResponseException(response()->json([
            'error' => 'invalid',
            'message' => $validator->errors()->first(),
            'fields' => $validator->errors()->toArray(),
        ], 422));
    }
}
