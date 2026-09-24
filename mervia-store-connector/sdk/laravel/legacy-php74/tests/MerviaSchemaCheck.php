<?php

/** A small JSON Schema checker for the contract's schemas (PHP 7.4 twin of the Laravel tests' one). */
final class MerviaSchemaCheck
{
    public static function contract(string $file): array
    {
        $path = __DIR__ . '/../../../../contract/schemas/' . $file;
        if (!is_file($path)) {
            throw new RuntimeException("Contract schema not found at {$path}; mount the whole repository (see README)");
        }
        return json_decode(file_get_contents($path), true);
    }

    public static function errors($data, array $schema, ?array $root = null, string $at = '$'): array
    {
        $root = $root === null ? $schema : $root;
        if (isset($schema['$ref'])) {
            $ref = $schema['$ref'];
            unset($schema['$ref']);
            $base = 'https://mervia.ai/store-connector/schemas/';
            if (strpos($ref, $base) === 0) {   // a sibling file in contract/schemas/
                $parts = explode('#', substr($ref, strlen($base)) . '#', 2);
                $root = self::contract($parts[0]);
                $ref = '#' . $parts[1];
            }
            $target = $root;
            if ($ref !== '#' && $ref !== '#/') {
                foreach (explode('/', substr($ref, 2)) as $part) {
                    $target = $target[$part];
                }
            }
            return self::errors($data, $target + $schema, $root, $at);
        }
        if (isset($schema['oneOf'])) {
            $n = 0;
            foreach ($schema['oneOf'] as $s) {
                $n += self::errors($data, $s, $root, $at) === array() ? 1 : 0;
            }
            return $n === 1 ? array() : array("{$at}: matches {$n} of oneOf");
        }
        $type = self::typeOf($data);
        if (isset($schema['type']) && !in_array($type, (array) $schema['type'], true)
            && !($type === 'integer' && in_array('number', (array) $schema['type'], true))) {
            return array("{$at}: expected " . implode('|', (array) $schema['type']) . ", got {$type}");
        }
        $errors = array();
        if (isset($schema['enum']) && !in_array($data, $schema['enum'], true)) {
            $errors[] = "{$at}: not in enum";
        }
        if (is_string($data)) {
            if (isset($schema['pattern']) && !preg_match('/' . str_replace('/', '\/', $schema['pattern']) . '/u', $data)) {
                $errors[] = "{$at}: does not match {$schema['pattern']}";
            }
            if (isset($schema['minLength']) && mb_strlen($data) < $schema['minLength']) {
                $errors[] = "{$at}: too short";
            }
            if (isset($schema['format']) && $schema['format'] === 'date-time'
                && !preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/', $data)) {
                $errors[] = "{$at}: not a date-time";
            }
        }
        if ((is_int($data) || is_float($data)) && isset($schema['minimum']) && $data < $schema['minimum']) {
            $errors[] = "{$at}: below minimum";
        }
        if ($type === 'array' && isset($schema['items'])) {
            if (isset($schema['minItems']) && count($data) < $schema['minItems']) {
                $errors[] = "{$at}: too few items";
            }
            foreach ($data as $i => $item) {
                $errors = array_merge($errors, self::errors($item, $schema['items'], $root, "{$at}[{$i}]"));
            }
        }
        if ($type === 'object' && isset($schema['properties'])) {
            foreach (isset($schema['required']) ? $schema['required'] : array() as $key) {
                if (!array_key_exists($key, $data)) {
                    $errors[] = "{$at}: missing {$key}";
                }
            }
            foreach ($schema['properties'] as $key => $sub) {
                if (array_key_exists($key, $data)) {
                    $errors = array_merge($errors, self::errors($data[$key], $sub, $root, "{$at}.{$key}"));
                }
            }
        }
        return $errors;
    }

    private static function typeOf($v): string
    {
        if ($v === null) return 'null';
        if (is_bool($v)) return 'boolean';
        if (is_int($v)) return 'integer';
        if (is_float($v)) return 'number';
        if (is_string($v)) return 'string';
        if (is_array($v)) return ($v !== array() && array_keys($v) === range(0, count($v) - 1)) ? 'array' : 'object';
        return 'unknown';
    }
}
