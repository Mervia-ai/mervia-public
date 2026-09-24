<?php

use PHPUnit\Framework\TestCase;

class MerviaOrdersTest extends TestCase
{
    /** Seven paid orders, updated_at ascending; #3 refunded, #5 cancelled. */
    private function rows(): array
    {
        $rows = array();
        for ($i = 1; $i <= 7; $i++) {
            $status = $i === 3 ? 'refunded' : ($i === 5 ? 'cancelled' : 'paid');
            $rows[] = array(
                'id' => 10040 + $i,
                'number' => '#' . (10040 + $i),
                'status' => $status,
                'paid_at' => sprintf('2026-09-%02dT10:00:00Z', 10 + $i),
                'updated_at' => sprintf('2026-09-%02dT12:00:00Z', 10 + $i),
                'currency' => 'usd',
                'subtotal' => '129.5',
                'total' => 136.16,
                'refunded_total' => $status === 'paid' ? 0 : ($status === 'cancelled' ? '136.16' : '20'),
                'line_items' => array(array('product_id' => 101, 'variant_id' => null, 'quantity' => 1, 'price' => '129.5')),
                'mervia_attribution' => $i % 2 ? 'v1.9f2c1a7b' : null,
            );
        }
        return $rows;
    }

    private $calls = array();

    /** A query callback over the in-memory rows, keeping the contract's ordering rules. */
    private function orders(?array $rows = null): MerviaOrders
    {
        $rows = $rows === null ? $this->rows() : $rows;
        $calls = &$this->calls;
        return new MerviaOrders(function (?string $since, ?array $after, int $take) use ($rows, &$calls): array {
            $calls[] = array($since, $after, $take);
            $out = array();
            foreach ($rows as $r) {
                if ($since !== null && $r['updated_at'] < $since) {
                    continue;
                }
                if ($after !== null && array($r['updated_at'], (string) $r['id']) <= array($after['updated_at'], (string) $after['id'])) {
                    continue;
                }
                $out[] = $r;
            }
            return array_slice($out, 0, $take);
        });
    }

    private function page(MerviaOrders $orders, array $params): array
    {
        $r = $orders->handleList($params);
        $this->assertSame(200, $r['status'], $r['body']);
        return json_decode($r['body'], true);
    }

    public function test_pages_through_every_order_once_and_matches_the_schema(): void
    {
        $orders = $this->orders();
        $schema = MerviaSchemaCheck::contract('order.schema.json');
        $ids = array();
        $cursor = null;
        for ($pages = 0; $pages < 5; $pages++) {
            $page = $this->page($orders, array('limit' => '3', 'cursor' => $cursor));
            foreach ($page['items'] as $item) {
                $this->assertSame(array(), MerviaSchemaCheck::errors($item, $schema), json_encode($item));
                $ids[] = $item['id'];
            }
            $cursor = $page['next_cursor'];
            if ($cursor === null) {
                break;
            }
        }
        $this->assertSame(array(10041, 10042, 10043, 10044, 10045, 10046, 10047), $ids);
        $this->assertSame(3, $pages + 1, 'three pages of 3, 3, 1');
        $this->assertSame(4, $this->calls[0][2], 'asks for limit + 1 rows to learn whether there is more');
        $first = $this->page($orders, array())['items'][0];
        $this->assertSame(array('USD', '129.50', '136.16', '0.00', 'paid'), array($first['currency'], $first['subtotal'], $first['total'], $first['refunded_total'], $first['status']));
        $this->assertNull($first['line_items'][0]['variant_id']);
    }

    public function test_updated_since_reaches_the_callback_and_narrows_the_list(): void
    {
        $page = $this->page($this->orders(), array('updated_since' => '2026-09-16T00:00:00Z'));
        $this->assertSame(array(10046, 10047), array_column($page['items'], 'id'));
        $this->assertNull($page['next_cursor']);
        $this->assertSame('2026-09-16T00:00:00Z', $this->calls[0][0]);
        $this->assertSame(array('items' => array(), 'next_cursor' => null), $this->page($this->orders(), array('updated_since' => '2999-01-01T00:00:00Z')));
    }

    public function test_bad_parameters_answer_422_in_the_contract_error_shape(): void
    {
        $orders = $this->orders();
        foreach (array(array('limit' => '0'), array('limit' => '251'), array('limit' => 'ten'), array('cursor' => 'not-ours'), array('updated_since' => 'yesterday')) as $bad) {
            $r = $orders->handleList($bad);
            $this->assertSame(422, $r['status'], json_encode($bad));
            $this->assertSame('invalid', json_decode($r['body'], true)['error']);
        }
        $this->assertSame(array(), $this->calls, 'nothing queried');
    }

    public function test_cursor_round_trips_ids_of_both_kinds(): void
    {
        foreach (array(10042, 'A-1/b') as $id) {
            $this->assertSame(array('updated_at' => '2026-09-12T12:00:00Z', 'id' => $id), MerviaOrders::decodeCursor(MerviaOrders::encodeCursor('2026-09-12T12:00:00Z', $id)));
        }
        $this->assertNull(MerviaOrders::decodeCursor(base64_encode('{"u":1}')));
    }

    public function test_personal_data_or_an_unpaid_row_is_refused_not_served(): void
    {
        $rows = $this->rows();
        $rows[0]['customer_email'] = 'jane@example.com';
        try {
            $this->orders($rows)->handleList(array());
            $this->fail('expected an exception');
        } catch (InvalidArgumentException $e) {
            $this->assertStringContainsString('personal data', $e->getMessage());
        }
        $rows = $this->rows();
        $rows[1]['status'] = 'pending';
        $this->expectException(InvalidArgumentException::class);
        $this->expectExceptionMessage('only paid orders are listed');
        $this->orders($rows)->handleList(array());
    }
}
