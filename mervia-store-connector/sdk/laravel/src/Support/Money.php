<?php

namespace Mervia\StoreConnector\Support;

use InvalidArgumentException;

/**
 * Money as the contract wants it: a decimal string with two decimals, e.g. "129.00".
 *
 * Integers and floats are whole currency units (not cents). A string is sent as given, padded
 * to at least two decimals ("129.5" -> "129.50", "1.250" stays "1.250" for three-decimal
 * currencies). A float with more than two decimals is refused rather than rounded: pass a string.
 */
final class Money
{
    public static function format(string|int|float $amount, string $field = 'amount'): string
    {
        if (is_int($amount)) {
            return $amount . '.00';
        }
        if (is_float($amount)) {
            if (!is_finite($amount)) {
                throw new InvalidArgumentException("{$field} must be a finite number");
            }
            if (abs(round($amount, 2) - $amount) > 1e-9) {
                throw new InvalidArgumentException("{$field} has more than two decimals; pass it as a string");
            }
            return number_format($amount, 2, '.', '');
        }
        $amount = trim($amount);
        if (!preg_match('/^(-?)(\d+)(?:\.(\d+))?$/', $amount, $m)) {
            throw new InvalidArgumentException("{$field} must be a decimal string, e.g. \"129.00\"");
        }
        return $m[1] . $m[2] . '.' . str_pad($m[3] ?? '', 2, '0');
    }
}
