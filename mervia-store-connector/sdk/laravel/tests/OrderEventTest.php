<?php

namespace Mervia\StoreConnector\Tests;

use DateTimeImmutable;
use InvalidArgumentException;
use Mervia\StoreConnector\Webhook\OrderEvent;
use Mervia\StoreConnector\Webhook\ProductEvent;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase as PlainTestCase;

class OrderEventTest extends PlainTestCase
{
    private function paid(array $overrides = []): array
    {
        return OrderEvent::paid(...$overrides + $this->args());
    }

    private function args(): array
    {
        return [
            'storeId' => 'example-us',
            'id' => 10042,
            'number' => '#10042',
            'paidAt' => new DateTimeImmutable('2026-09-23T10:15:00-07:00'),
            'currency' => 'usd',
            'subtotal' => '129.5',
            'discountTotal' => 10,
            'shipping' => 5.0,
            'tax' => '11.66',
            'total' => 136.16,
            'lineItems' => [['product_id' => 'sku-example', 'variant_id' => 77, 'sku' => 'EX-M1', 'quantity' => 1, 'price' => '129.50']],
            'merviaAttribution' => 'v1.9f2c1a7b',
            'customerKey' => OrderEvent::customerKey(' Buyer@Example.com '),
        ];
    }

    public function test_full_payload_matches_the_contract_schema(): void
    {
        $payload = $this->paid();

        $this->assertSame([], SchemaCheck::errors($payload, SchemaCheck::contract('order-event.schema.json')));
        $this->assertSame('order.paid', $payload['event']);
        $this->assertMatchesRegularExpression('/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $payload['event_id']);
        $order = $payload['order'];
        $this->assertSame(['129.50', '10.00', '5.00', '11.66', '136.16'], [$order['subtotal'], $order['discount_total'], $order['shipping'], $order['tax'], $order['total']]);
        $this->assertSame('USD', $order['currency']);
        $this->assertSame('2026-09-23T10:15:00-07:00', $order['paid_at']);
        $this->assertSame('129.50', $order['line_items'][0]['price']);
        $this->assertSame(hash('sha256', 'buyer@example.com'), $order['customer_key']);
    }

    public function test_every_emitted_order_key_is_a_schema_property(): void
    {
        $schema = SchemaCheck::contract('order-event.schema.json');
        $known = array_keys(SchemaCheck::contract('order.schema.json')['properties']);
        $this->assertSame([], array_diff(array_keys($this->paid()['order']), $known));
        $this->assertSame([], array_diff(array_keys($this->paid()), array_keys($schema['properties'])));
    }

    public function test_minimal_payload_sends_null_attribution_and_omits_optionals(): void
    {
        $payload = OrderEvent::make(
            event: 'order.refunded',
            storeId: 'example-us',
            id: 'A-1',
            paidAt: '2026-09-23T17:15:00Z',
            currency: 'EUR',
            total: '20',
            lineItems: [['product_id' => 5, 'quantity' => 2, 'price' => 10]],
            refundedTotal: '20.00',
        );

        $this->assertSame([], SchemaCheck::errors($payload, SchemaCheck::contract('order-event.schema.json')));
        $this->assertArrayHasKey('mervia_attribution', $payload['order']);
        $this->assertNull($payload['order']['mervia_attribution']);
        $this->assertArrayNotHasKey('customer_key', $payload['order']);
        $this->assertArrayNotHasKey('number', $payload['order']);
        $this->assertSame('20.00', $payload['order']['refunded_total']);
        $this->assertSame('refunded', $payload['order']['status']);
    }

    public function test_status_and_refunded_total_follow_the_event(): void
    {
        $paid = $this->paid();
        $this->assertSame(['paid', '0.00'], [$paid['order']['status'], $paid['order']['refunded_total']]);
        $this->assertMatchesRegularExpression('/^\d{4}-\d{2}-\d{2}T/', $paid['order']['updated_at']);

        $cancelled = OrderEvent::cancelled(...['updatedAt' => '2026-09-24T10:00:00Z'] + $this->args());
        $this->assertSame(['cancelled', '136.16', '2026-09-24T10:00:00Z'], [$cancelled['order']['status'], $cancelled['order']['refunded_total'], $cancelled['order']['updated_at']]);
        $this->assertSame([], SchemaCheck::errors($cancelled, SchemaCheck::contract('order-event.schema.json')));

        $this->expectException(InvalidArgumentException::class);
        $this->expectExceptionMessage('refundedTotal');
        OrderEvent::refunded(...$this->args());
    }

    public function test_event_ids_are_unique_unless_given(): void
    {
        $this->assertNotSame($this->paid()['event_id'], $this->paid()['event_id']);
        $this->assertSame('evt-1', $this->paid(['eventId' => 'evt-1'])['event_id']);
    }

    public static function invalid(): array
    {
        return [
            'unknown event' => [['event' => 'order.shipped']],
            'bad currency' => [['currency' => 'dollars']],
            'float with three decimals' => [['total' => 1.005]],
            'comma decimal' => [['total' => '12,00']],
            'timestamp without seconds' => [['paidAt' => '2026-09-23T10:00Z']],
            'impossible date' => [['paidAt' => '2026-02-30T10:00:00Z']],
            'hour 25' => [['paidAt' => '2026-09-23T25:00:00Z']],
            'email as a value in extra' => [['extra' => ['customer' => 'Buyer@Example.com']]],
            'array variant id' => [['lineItems' => [['product_id' => 1, 'variant_id' => [1], 'quantity' => 1, 'price' => 1]]]],
            'money word' => [['total' => 'ten']],
            'no line items' => [['lineItems' => []]],
            'line item without price' => [['lineItems' => [['product_id' => 1, 'quantity' => 1]]]],
            'zero quantity' => [['lineItems' => [['product_id' => 1, 'quantity' => 0, 'price' => 1]]]],
            'timestamp without zone' => [['paidAt' => '2026-09-23 10:00:00']],
            'email as customer key' => [['customerKey' => 'buyer@example.com']],
            'empty id' => [['id' => ' ']],
            'pii in extra' => [['extra' => ['customer_email' => 'a@b.c']]],
            'nested pii in extra' => [['extra' => ['meta' => ['shipping_address' => 'x']]]],
            'name in extra' => [['extra' => ['FirstName' => 'Ann']]],
            'phone in line item' => [['lineItems' => [['product_id' => 1, 'quantity' => 1, 'price' => 1, 'phone' => '555']]]],
            'extra overriding a field' => [['extra' => ['total' => '0.00']]],
        ];
    }

    #[DataProvider('invalid')]
    public function test_refuses_invalid_input(array $overrides): void
    {
        $this->expectException(InvalidArgumentException::class);
        $event = $overrides['event'] ?? 'order.paid';
        unset($overrides['event']);
        $args = $overrides + [
            'storeId' => 'example-us', 'id' => 1, 'paidAt' => '2026-09-23T10:00:00Z', 'currency' => 'USD',
            'total' => '1.00', 'lineItems' => [['product_id' => 1, 'quantity' => 1, 'price' => '1.00']],
        ];
        OrderEvent::make($event, ...$args);
    }

    public function test_money_keeps_three_decimal_currencies_exact(): void
    {
        $payload = $this->paid(['currency' => 'KWD', 'total' => '1.250', 'subtotal' => '-3', 'shipping' => 0.1]);
        $this->assertSame(['1.250', '-3.00', '0.10'], [$payload['order']['total'], $payload['order']['subtotal'], $payload['order']['shipping']]);
        $this->assertSame([], SchemaCheck::errors($payload, SchemaCheck::contract('order-event.schema.json')));
    }

    public function test_non_personal_extra_passes_through(): void
    {
        $payload = $this->paid(['extra' => ['channel' => 'web']]);
        $this->assertSame('web', $payload['order']['channel']);
    }

    public function test_product_event_matches_the_contract_schema(): void
    {
        $schema = SchemaCheck::contract('product-event.schema.json');
        $updated = ProductEvent::updated('example-us', 42, new DateTimeImmutable('2026-09-23T10:00:00Z'));
        $deleted = ProductEvent::deleted('example-us', 'sku-1');

        $this->assertSame([], SchemaCheck::errors($updated, $schema));
        $this->assertSame([], SchemaCheck::errors($deleted, $schema));
        $this->assertSame('product.deleted', $deleted['event']);
        $this->assertArrayNotHasKey('updated_at', $deleted);

        $this->expectException(InvalidArgumentException::class);
        ProductEvent::make('product.created', 'example-us', 1);
    }

    public function test_schema_check_itself_catches_errors(): void
    {
        $payload = $this->paid();
        $payload['order']['total'] = '12,00';
        unset($payload['event_id']);
        $errors = SchemaCheck::errors($payload, SchemaCheck::contract('order-event.schema.json'));
        $this->assertContains('$: missing event_id', $errors);
        $this->assertNotEmpty(array_filter($errors, fn ($e) => str_starts_with($e, '$.order.total')));
    }
}
