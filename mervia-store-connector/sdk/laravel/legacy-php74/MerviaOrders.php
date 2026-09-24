<?php

/**
 * Item 8: GET /orders, PHP 7.4, no dependencies. Turns your paid-order rows into the contract's
 * list response (contract/openapi.yaml, schemas/order.schema.json), with cursor pagination and
 * updated_since. Mervia reads it about once an hour.
 *
 *   $orders = new MerviaOrders(function (?string $updatedSince, ?array $after, int $take) use ($pdo): array {
 *       // Up to $take PAID orders, ordered by updated_at then id, with updated_at >= $updatedSince
 *       // when given, and strictly after $after (['updated_at' => ..., 'id' => ...]) when given.
 *       // Each row uses the contract's keys (see MerviaOrderEvent::order): id, number, status,
 *       // paid_at, updated_at, currency, subtotal, discount_total, shipping, tax, total,
 *       // refunded_total, line_items, mervia_attribution, customer_key. No customer name,
 *       // email, phone or address.
 *       ...
 *   });
 *   MerviaOrders::respond($orders->handleList($_GET));   // behind your Mervia API-key check
 *
 * Rules the callback must keep: only orders that have been paid are listed; updated_at changes
 * when the order is paid, refunded or cancelled; refunded_total is the running total refunded
 * so far ("0.00" until something is) and a cancelled order is a full refund.
 */
final class MerviaOrders
{
    const MAX_LIMIT = 250;

    /** @var callable(?string, ?array, int): array */
    private $query;

    public function __construct(callable $query)
    {
        $this->query = $query;
    }

    /**
     * @param array $params the query string, e.g. $_GET: limit, cursor, updated_since
     * @return array{status: int, body: string} 200 with the page; 422 in the contract's error shape for a bad parameter
     */
    public function handleList(array $params): array
    {
        $limit = isset($params['limit']) ? $params['limit'] : self::MAX_LIMIT;
        if (!is_int($limit) && !(is_string($limit) && ctype_digit($limit))) {
            return self::error(422, 'limit must be an integer between 1 and ' . self::MAX_LIMIT);
        }
        $limit = (int) $limit;
        if ($limit < 1 || $limit > self::MAX_LIMIT) {
            return self::error(422, 'limit must be an integer between 1 and ' . self::MAX_LIMIT);
        }
        $since = isset($params['updated_since']) && $params['updated_since'] !== '' ? $params['updated_since'] : null;
        if ($since !== null && !MerviaOrderEvent::isTimestamp($since)) {
            return self::error(422, 'updated_since must be ISO 8601 with a timezone, e.g. 2026-09-23T10:00:00Z');
        }
        $after = null;
        if (isset($params['cursor']) && $params['cursor'] !== '') {
            $after = self::decodeCursor((string) $params['cursor']);
            if ($after === null) {
                return self::error(422, 'cursor is not one this endpoint issued');
            }
        }
        $rows = call_user_func($this->query, $since, $after, $limit + 1);
        if (!is_array($rows)) {
            throw new UnexpectedValueException('the query callback must return an array of order rows');
        }
        $rows = array_values($rows);
        $more = count($rows) > $limit;
        $rows = array_slice($rows, 0, $limit);
        $items = array();
        foreach ($rows as $row) {
            $items[] = MerviaOrderEvent::order($row);
        }
        $last = $more ? $items[count($items) - 1] : null;
        $body = array('items' => $items, 'next_cursor' => $last === null ? null : self::encodeCursor($last['updated_at'], $last['id']));
        return array('status' => 200, 'body' => json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
    }

    /** Send a handleList() answer: status, Content-Type and body. */
    public static function respond(array $response): void
    {
        http_response_code($response['status']);
        header('Content-Type: application/json');
        echo $response['body'];
    }

    /** @param string|int $id */
    public static function encodeCursor(string $updatedAt, $id): string
    {
        return rtrim(strtr(base64_encode(json_encode(array('u' => $updatedAt, 'i' => $id))), '+/', '-_'), '=');
    }

    /** @return array{updated_at: string, id: string|int}|null null when the cursor is not one we issued */
    public static function decodeCursor(string $cursor): ?array
    {
        $raw = base64_decode(strtr($cursor, '-_', '+/'), true);
        $data = $raw === false ? null : json_decode($raw, true);
        if (!is_array($data) || !isset($data['u'], $data['i']) || !is_string($data['u']) || (!is_string($data['i']) && !is_int($data['i']))) {
            return null;
        }
        return array('updated_at' => $data['u'], 'id' => $data['i']);
    }

    private static function error(int $status, string $message): array
    {
        return array('status' => $status, 'body' => json_encode(array('error' => 'invalid', 'message' => $message)));
    }
}
