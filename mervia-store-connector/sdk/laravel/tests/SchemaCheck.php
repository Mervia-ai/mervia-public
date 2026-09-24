<?php

namespace Mervia\StoreConnector\Tests;

/**
 * A deliberately small JSON Schema checker for the contract's own schemas: type, required,
 * properties, enum, pattern, minLength, minItems, minimum, items, oneOf and local $ref.
 * Returns a list of error strings; empty means valid.
 */
final class SchemaCheck
{
    private const SCHEMA_BASE = 'https://mervia.ai/store-connector/schemas/';

    public static function contract(string $file): array
    {
        $path = __DIR__ . '/../../../contract/schemas/' . $file;
        if (!is_file($path)) {
            throw new \RuntimeException("Contract schema not found at {$path}; mount the whole repository (see README)");
        }
        return json_decode(file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
    }

    /** contract/openapi.yaml as an array; a component is checked with ['$ref' => '#/components/schemas/X']. */
    public static function openapi(): array
    {
        return \Symfony\Component\Yaml\Yaml::parseFile(__DIR__ . '/../../../contract/openapi.yaml');
    }

    public static function errors(mixed $data, array $schema, ?array $root = null, string $at = '$'): array
    {
        $root ??= $schema;
        if (isset($schema['$ref'])) {
            $ref = $schema['$ref'];
            if (str_starts_with($ref, self::SCHEMA_BASE)) {   // a sibling file in contract/schemas/
                [$file, $fragment] = explode('#', substr($ref, strlen(self::SCHEMA_BASE)) . '#', 2);
                $root = self::contract($file);
                $ref = '#' . $fragment;
            }
            $target = $root;
            if ($ref !== '#' && $ref !== '#/') {
                foreach (explode('/', substr($ref, 2)) as $part) {
                    $target = $target[$part];
                }
            }
            return self::errors($data, $target + array_diff_key($schema, ['$ref' => 1]), $root, $at);
        }
        if (isset($schema['oneOf'])) {
            $matches = count(array_filter($schema['oneOf'], fn ($s) => self::errors($data, $s, $root, $at) === []));
            return $matches === 1 ? [] : ["{$at}: matches {$matches} of oneOf"];
        }
        $errors = [];
        $emptyOk = $data === [] && array_intersect(['array', 'object'], (array) ($schema['type'] ?? [])) !== [];
        if (isset($schema['type']) && !$emptyOk && !in_array(self::typeOf($data), (array) $schema['type'], true)
            && !(self::typeOf($data) === 'integer' && in_array('number', (array) $schema['type'], true))) {
            return ["{$at}: expected " . implode('|', (array) $schema['type']) . ', got ' . self::typeOf($data)];
        }
        if (isset($schema['enum']) && !in_array($data, $schema['enum'], true)) {
            $errors[] = "{$at}: not in enum";
        }
        if (is_string($data)) {
            if (isset($schema['pattern']) && !preg_match('/' . str_replace('/', '\/', $schema['pattern']) . '/u', $data)) {
                $errors[] = "{$at}: does not match {$schema['pattern']}";
            }
            if (isset($schema['minLength']) && mb_strlen($data) < $schema['minLength']) {
                $errors[] = "{$at}: shorter than {$schema['minLength']}";
            }
            if (($schema['format'] ?? null) === 'date-time' && !preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/', $data)) {
                $errors[] = "{$at}: not a date-time";
            }
        }
        if ((is_int($data) || is_float($data)) && isset($schema['minimum']) && $data < $schema['minimum']) {
            $errors[] = "{$at}: below {$schema['minimum']}";
        }
        if (is_array($data) && array_is_list($data) && isset($schema['items'])) {
            if (isset($schema['minItems']) && count($data) < $schema['minItems']) {
                $errors[] = "{$at}: fewer than {$schema['minItems']} items";
            }
            foreach ($data as $i => $item) {
                $errors = array_merge($errors, self::errors($item, $schema['items'], $root, "{$at}[{$i}]"));
            }
        }
        if (is_array($data) && isset($schema['properties'])) {
            foreach ($schema['required'] ?? [] as $key) {
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

    private static function typeOf(mixed $v): string
    {
        return match (true) {
            $v === null => 'null',
            is_bool($v) => 'boolean',
            is_int($v) => 'integer',
            is_float($v) => 'number',
            is_string($v) => 'string',
            is_array($v) && array_is_list($v) && $v !== [] => 'array',
            is_array($v) => 'object',
            default => 'unknown',
        };
    }
}
