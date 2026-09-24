<?php

/**
 * Item 6: the product-page document Mervia pushes to PUT /products/{id}/content, PHP 7.4,
 * no dependencies. Keeps the document, ignores an older version, prints it verbatim.
 *
 *   $content = MerviaProductContent::withPdo($pdo);            // table mervia_product_content
 *   // or: new MerviaProductContent($load, $save, $delete);    // your own storage callbacks
 *
 *   // in the endpoint your store serves under Mervia's API key:
 *   MerviaProductContent::respond($content->handlePut($id, file_get_contents('php://input')));
 *   MerviaProductContent::respond($content->handleDelete($id));
 *
 *   // in the product template (server-rendered; prints nothing when nothing is stored):
 *   <head> ... <?php $content->printHead($product['id']); ?> </head>
 *   ... <?php $content->printBody($product['id']); ?> ...
 */
final class MerviaProductContent
{
    /** @var callable(string): ?array */
    private $load;
    /** @var callable(string, array): void */
    private $save;
    /** @var callable(string): void */
    private $delete;
    private $memo = array();

    /**
     * @param callable $load   function (string $productId): ?array  — ['version' => int, 'head_html' => string, 'body_html' => string] or null
     * @param callable $save   function (string $productId, array $document): void — replaces any stored document
     * @param callable $delete function (string $productId): void — nothing stored is fine
     */
    public function __construct(callable $load, callable $save, callable $delete)
    {
        $this->load = $load;
        $this->save = $save;
        $this->delete = $delete;
    }

    /** Storage in a table with columns product_id, version, head_html, body_html, updated_at (see createTableSql). */
    public static function withPdo(PDO $pdo, string $table = 'mervia_product_content'): self
    {
        if (!preg_match('/^[A-Za-z_][A-Za-z0-9_]*$/', $table)) {
            throw new InvalidArgumentException('table name must be a plain identifier');
        }
        $load = function (string $id) use ($pdo, $table): ?array {
            $st = $pdo->prepare("SELECT version, head_html, body_html FROM {$table} WHERE product_id = ?");
            $st->execute(array($id));
            $row = $st->fetch(PDO::FETCH_ASSOC);
            if (!$row) {
                return null;
            }
            return array('version' => (int) $row['version'], 'head_html' => (string) $row['head_html'], 'body_html' => (string) $row['body_html']);
        };
        $save = function (string $id, array $doc) use ($pdo, $table): void {
            $now = gmdate('Y-m-d H:i:s');
            $st = $pdo->prepare("UPDATE {$table} SET version = ?, head_html = ?, body_html = ?, updated_at = ? WHERE product_id = ?");
            $st->execute(array($doc['version'], $doc['head_html'], $doc['body_html'], $now, $id));
            if ($st->rowCount() === 0) {
                $st = $pdo->prepare("INSERT INTO {$table} (product_id, version, head_html, body_html, updated_at) VALUES (?, ?, ?, ?, ?)");
                $st->execute(array($id, $doc['version'], $doc['head_html'], $doc['body_html'], $now));
            }
        };
        $delete = function (string $id) use ($pdo, $table): void {
            $st = $pdo->prepare("DELETE FROM {$table} WHERE product_id = ?");
            $st->execute(array($id));
        };
        return new self($load, $save, $delete);
    }

    /** Portable DDL for the table withPdo() expects; adjust column types to your database if you like. */
    public static function createTableSql(string $table = 'mervia_product_content'): string
    {
        return "CREATE TABLE {$table} (product_id VARCHAR(191) NOT NULL PRIMARY KEY, version BIGINT NOT NULL, "
            . "head_html TEXT NOT NULL, body_html TEXT NOT NULL, updated_at DATETIME NULL)";
    }

    /**
     * Handle PUT /products/{id}/content. $body is the raw JSON request body (or the decoded array).
     * 204 when stored, and also when an older version was ignored; 400 when the body is not JSON;
     * 422 in the contract's error shape when it does not match the ProductContent schema.
     * Check the product exists first and answer 404 yourself.
     *
     * @param string|int $productId
     * @param string|array $body
     * @return array{status: int, body: string}
     */
    public function handlePut($productId, $body): array
    {
        $id = self::id($productId);
        if ($id === null) {
            return self::error(404, 'not_found', 'unknown product');
        }
        $data = is_array($body) ? $body : json_decode((string) $body, true);
        if (!is_array($data)) {
            return self::error(400, 'invalid', 'the body must be a JSON object');
        }
        if (!isset($data['version']) || !is_int($data['version']) || $data['version'] < 1) {
            return self::error(422, 'invalid', 'version must be an integer of at least 1');
        }
        foreach (array('head_html', 'body_html') as $part) {
            if (!array_key_exists($part, $data) || ($data[$part] !== null && !is_string($data[$part]))) {
                return self::error(422, 'invalid', $part . ' must be present, as a string');
            }
        }
        $doc = array('version' => $data['version'], 'head_html' => (string) $data['head_html'], 'body_html' => (string) $data['body_html']);
        $current = call_user_func($this->load, $id);
        if (!(is_array($current) && isset($current['version']) && $doc['version'] < (int) $current['version'])) {
            call_user_func($this->save, $id, $doc);
        }
        unset($this->memo[$id]);
        return array('status' => 204, 'body' => '');
    }

    /** Handle DELETE /products/{id}/content: 204, also when nothing was stored. @param string|int $productId */
    public function handleDelete($productId): array
    {
        $id = self::id($productId);
        if ($id === null) {
            return self::error(404, 'not_found', 'unknown product');
        }
        call_user_func($this->delete, $id);
        unset($this->memo[$id]);
        return array('status' => 204, 'body' => '');
    }

    /** Send a handlePut()/handleDelete() answer: status, Content-Type and body. */
    public static function respond(array $response): void
    {
        http_response_code($response['status']);
        if ($response['body'] !== '') {
            header('Content-Type: application/json');
            echo $response['body'];
        }
    }

    /** @param string|int|null $productId */
    public function printHead($productId): void
    {
        echo $this->fetch($productId)['head_html'];
    }

    /** @param string|int|null $productId */
    public function printBody($productId): void
    {
        echo $this->fetch($productId)['body_html'];
    }

    /** @param string|int|null $productId @return array{head_html: string, body_html: string} Never throws. */
    public function fetch($productId): array
    {
        $empty = array('head_html' => '', 'body_html' => '');
        try {
            $id = self::id($productId);
            if ($id === null) {
                return $empty;
            }
            if (!isset($this->memo[$id])) {
                $stored = call_user_func($this->load, $id);
                $this->memo[$id] = is_array($stored) ? array(
                    'head_html' => isset($stored['head_html']) && is_string($stored['head_html']) ? $stored['head_html'] : '',
                    'body_html' => isset($stored['body_html']) && is_string($stored['body_html']) ? $stored['body_html'] : '',
                ) : $empty;
            }
            return $this->memo[$id];
        } catch (Throwable $e) {
            return $empty;
        }
    }

    private static function id($productId): ?string
    {
        if ((!is_string($productId) && !is_int($productId)) || (string) $productId === '') {
            return null;
        }
        return (string) $productId;
    }

    private static function error(int $status, string $code, string $message): array
    {
        return array('status' => $status, 'body' => json_encode(array('error' => $code, 'message' => $message)));
    }
}
