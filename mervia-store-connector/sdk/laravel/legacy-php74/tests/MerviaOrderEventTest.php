<?php

use PHPUnit\Framework\TestCase;

class MerviaOrderEventTest extends TestCase
{
    private function order(array $overrides = array()): array
    {
        return array_merge(array(
            'id' => 10042,
            'number' => '#10042',
            'paid_at' => new DateTimeImmutable('2026-09-23T10:15:00-07:00'),
            'currency' => 'usd',
            'subtotal' => '129.5',
            'discount_total' => 10,
            'shipping' => 5.0,
            'tax' => '11.66',
            'total' => 136.16,
            'line_items' => array(array('product_id' => 'p1', 'variant_id' => 77, 'sku' => 'EX-M1', 'quantity' => 1, 'price' => '129.50')),
            'mervia_attribution' => 'v1.9f2c1a7b',
            'customer_key' => MerviaOrderEvent::customerKey(' Buyer@Example.com '),
        ), $overrides);
    }

    public function test_payload_matches_the_contract_schema(): void
    {
        $schema = MerviaSchemaCheck::contract('order-event.schema.json');
        foreach (MerviaOrderEvent::EVENTS as $event) {
            $p = MerviaOrderEvent::build($event, 'example-us', $this->order(array('refunded_total' => '1')));
            $this->assertSame(array(), MerviaSchemaCheck::errors($p, $schema), $event);
            $this->assertSame(array(), array_diff(array_keys($p['order']), array_keys(MerviaSchemaCheck::contract('order.schema.json')['properties'])));
            $this->assertSame(substr($event, 6), $p['order']['status']);
        }
        $o = $p['order'];
        $this->assertSame(array('129.50', '10.00', '5.00', '11.66', '136.16', '1.00'), array($o['subtotal'], $o['discount_total'], $o['shipping'], $o['tax'], $o['total'], $o['refunded_total']));
        $this->assertSame('USD', $o['currency']);
        $this->assertSame('2026-09-23T10:15:00-07:00', $o['paid_at']);
        $this->assertSame(hash('sha256', 'buyer@example.com'), $o['customer_key']);
        $this->assertMatchesRegularExpression('/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $p['event_id']);
    }

    public function test_minimal_payload_sends_null_attribution(): void
    {
        $p = MerviaOrderEvent::build('order.paid', 7, array(
            'id' => 'A1', 'paid_at' => '2026-09-23T17:00:00Z', 'currency' => 'EUR', 'total' => '5',
            'line_items' => array(array('product_id' => 1, 'quantity' => 1, 'price' => 5)),
        ));
        $this->assertSame(array(), MerviaSchemaCheck::errors($p, MerviaSchemaCheck::contract('order-event.schema.json')));
        $this->assertArrayHasKey('mervia_attribution', $p['order']);
        $this->assertNull($p['order']['mervia_attribution']);
        $this->assertArrayNotHasKey('number', $p['order']);
        $this->assertSame(array('paid', '0.00'), array($p['order']['status'], $p['order']['refunded_total']));
        $this->assertTrue(MerviaOrderEvent::isTimestamp($p['order']['updated_at']));
    }

    public function test_cancelled_is_a_full_refund_and_a_refund_needs_the_amount(): void
    {
        $p = MerviaOrderEvent::build('order.cancelled', 7, $this->order(array('updated_at' => '2026-09-24T10:00:00Z')));
        $this->assertSame(array('cancelled', '136.16', '2026-09-24T10:00:00Z'), array($p['order']['status'], $p['order']['refunded_total'], $p['order']['updated_at']));
        $this->expectException(InvalidArgumentException::class);
        $this->expectExceptionMessage('refunded_total');
        MerviaOrderEvent::build('order.refunded', 7, $this->order());
    }

    public function invalid(): array
    {
        return array(
            'unknown event' => array('order.shipped', array()),
            'missing total' => array('order.paid', array('total' => null)),
            'bad currency' => array('order.paid', array('currency' => 'dollars')),
            'float with three decimals' => array('order.paid', array('total' => 1.005)),
            'no seconds' => array('order.paid', array('paid_at' => '2026-09-23T10:00Z')),
            'impossible date' => array('order.paid', array('paid_at' => '2026-02-30T10:00:00Z')),
            'email as a value' => array('order.paid', array('number' => 'buyer@example.com')),
            'array variant id' => array('order.paid', array('line_items' => array(array('product_id' => 1, 'variant_id' => array(1), 'quantity' => 1, 'price' => 1)))),
            'no line items' => array('order.paid', array('line_items' => array())),
            'zero quantity' => array('order.paid', array('line_items' => array(array('product_id' => 1, 'quantity' => 0, 'price' => 1)))),
            'no timezone' => array('order.paid', array('paid_at' => '2026-09-23 10:00:00')),
            'email as customer key' => array('order.paid', array('customer_key' => 'a@b.c')),
            'email key' => array('order.paid', array('email' => 'a@b.c')),
            'typo key' => array('order.paid', array('totl' => '1.00')),
            'address in line item' => array('order.paid', array('line_items' => array(array('product_id' => 1, 'quantity' => 1, 'price' => 1, 'ship_address' => 'x')))),
        );
    }

    /** @dataProvider invalid */
    public function test_refuses_invalid_input(string $event, array $overrides): void
    {
        $this->expectException(InvalidArgumentException::class);
        MerviaOrderEvent::build($event, 'example-us', $this->order($overrides));
    }

    public function test_three_decimal_currencies_stay_exact(): void
    {
        $p = MerviaOrderEvent::build('order.paid', 'example-us', $this->order(array('currency' => 'KWD', 'total' => '1.250', 'shipping' => 0.1)));
        $this->assertSame(array('1.250', '0.10'), array($p['order']['total'], $p['order']['shipping']));
    }

    public function test_extra_is_checked_for_personal_data(): void
    {
        $p = MerviaOrderEvent::build('order.paid', 'example-us', $this->order(), array('channel' => 'web'));
        $this->assertSame('web', $p['order']['channel']);

        $this->expectException(InvalidArgumentException::class);
        MerviaOrderEvent::build('order.paid', 'example-us', $this->order(), array('meta' => array('customer_phone' => '555')));
    }

    public function test_product_events_match_the_contract_schema(): void
    {
        $schema = MerviaSchemaCheck::contract('product-event.schema.json');
        $this->assertSame(array(), MerviaSchemaCheck::errors(MerviaOrderEvent::product('product.updated', 'example-us', 42, '2026-09-23T10:00:00Z'), $schema));
        $this->assertSame(array(), MerviaSchemaCheck::errors(MerviaOrderEvent::product('product.deleted', 'example-us', 'p1'), $schema));
        $this->expectException(InvalidArgumentException::class);
        MerviaOrderEvent::product('product.created', 'example-us', 1);
    }
}
