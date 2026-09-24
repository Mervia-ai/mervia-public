<?php

use PHPUnit\Framework\TestCase;

class MerviaProductContentTest extends TestCase
{
    const HEAD = '<script type="application/ld+json" id="mervia-product-schema">{"@type":"Product","name":"A & B <ok>"}</script>';
    const BODY = '<section id="mervia-shopping-guide"><p>Tom & Jerry</p></section>';

    private $rows = array();
    private $loads = 0;

    private function withCallbacks(): MerviaProductContent
    {
        $rows = &$this->rows;
        $loads = &$this->loads;
        return new MerviaProductContent(
            function (string $id) use (&$rows, &$loads) { $loads++; return isset($rows[$id]) ? $rows[$id] : null; },
            function (string $id, array $doc) use (&$rows) { $rows[$id] = $doc; },
            function (string $id) use (&$rows) { unset($rows[$id]); }
        );
    }

    private function withSqlite(): MerviaProductContent
    {
        $pdo = new PDO('sqlite::memory:');
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->exec(MerviaProductContent::createTableSql());
        return MerviaProductContent::withPdo($pdo);
    }

    private function put(MerviaProductContent $c, $id, int $version, string $head, string $body): array
    {
        return $c->handlePut($id, json_encode(array('version' => $version, 'head_html' => $head, 'body_html' => $body)));
    }

    /** Both storages behave the same. */
    public function storages(): array
    {
        return array('callbacks' => array('withCallbacks'), 'pdo sqlite' => array('withSqlite'));
    }

    /** @dataProvider storages */
    public function test_put_stores_and_prints_verbatim(string $factory): void
    {
        $c = $this->$factory();
        $this->assertSame(array('status' => 204, 'body' => ''), $this->put($c, 42, 3, self::HEAD, self::BODY));

        $fresh = clone $c; // a new page request: nothing memoised
        ob_start();
        $fresh->printHead(42);
        $fresh->printBody('42');
        $this->assertSame(self::HEAD . self::BODY, ob_get_clean());
        $this->assertSame(array('head_html' => self::HEAD, 'body_html' => self::BODY), $fresh->fetch(42));
    }

    /** @dataProvider storages */
    public function test_lower_version_is_ignored_equal_or_higher_replaces(string $factory): void
    {
        $c = $this->$factory();
        $this->put($c, 1, 5, 'h5', 'b5');
        $this->assertSame(204, $this->put($c, 1, 4, 'h4', 'b4')['status'], 'ignored, but still 204');
        $this->assertSame('b5', $c->fetch(1)['body_html']);
        $this->put($c, 1, 5, 'h5x', 'b5x');
        $this->assertSame('b5x', $c->fetch(1)['body_html']);
        $this->put($c, 1, 6, '', 'b6');
        $this->assertSame(array('head_html' => '', 'body_html' => 'b6'), $c->fetch(1));
    }

    /** @dataProvider storages */
    public function test_delete_empties_the_page_and_is_fine_when_nothing_is_stored(string $factory): void
    {
        $c = $this->$factory();
        $this->put($c, 7, 1, 'h', 'b');
        $this->assertSame(array('status' => 204, 'body' => ''), $c->handleDelete(7));
        $this->assertSame(array('head_html' => '', 'body_html' => ''), $c->fetch(7));
        $this->assertSame(204, $c->handleDelete(7)['status']);
        $this->assertSame(204, $c->handleDelete('never')['status']);
    }

    public function test_invalid_bodies_answer_in_the_contract_error_shape(): void
    {
        $c = $this->withCallbacks();
        $r = $c->handlePut(1, 'not json');
        $this->assertSame(400, $r['status']);
        $this->assertSame('invalid', json_decode($r['body'], true)['error']);

        foreach (array(
            array('head_html' => '', 'body_html' => ''),                             // no version
            array('version' => 0, 'head_html' => '', 'body_html' => ''),             // below 1
            array('version' => '2', 'head_html' => '', 'body_html' => ''),           // not an integer
            array('version' => 1, 'body_html' => ''),                                // head missing
            array('version' => 1, 'head_html' => array(), 'body_html' => ''),        // not a string
        ) as $bad) {
            $r = $c->handlePut(1, json_encode($bad));
            $this->assertSame(422, $r['status'], json_encode($bad));
            $this->assertSame('invalid', json_decode($r['body'], true)['error']);
        }
        $this->assertSame(array(), $this->rows, 'nothing stored');
        $this->assertSame(204, $c->handlePut(1, array('version' => 1, 'head_html' => null, 'body_html' => 'b'))['status'], 'null reads as empty');
        $this->assertSame(array('version' => 1, 'head_html' => '', 'body_html' => 'b'), $this->rows['1']);
        $this->assertSame(404, $c->handlePut('', '{}')['status']);
        $this->assertSame(404, $c->handleDelete(null)['status']);
    }

    public function test_head_and_body_share_one_load_and_a_put_refreshes_it(): void
    {
        $c = $this->withCallbacks();
        $this->put($c, 3, 1, 'h1', 'b1');   // one load, for the version rule
        $this->loads = 0;
        $c->printHead(3);
        $c->printBody(3);
        $this->expectOutputString('h1b1h2b2');
        $this->assertSame(1, $this->loads, 'head and body share one load');
        $this->put($c, 3, 2, 'h2', 'b2');   // forgets the memo
        $c->printHead(3);
        $c->printBody(3);
        $this->assertSame(3, $this->loads);
    }

    public function test_reading_never_throws_or_prints_when_storage_fails_or_the_id_is_bad(): void
    {
        $broken = new MerviaProductContent(
            function (string $id) { throw new RuntimeException('db down'); },
            function (string $id, array $doc) {},
            function (string $id) {}
        );
        $this->expectOutputString('');
        $broken->printHead(1);
        $broken->printBody(1);
        $c = $this->withCallbacks();
        $c->printHead(null);
        $c->printBody('');
        $c->printBody(array('id' => 1));
        $this->assertSame(0, $this->loads);
    }

    public function test_pdo_table_name_must_be_an_identifier(): void
    {
        $this->expectException(InvalidArgumentException::class);
        MerviaProductContent::withPdo(new PDO('sqlite::memory:'), 'mervia; drop table x');
    }
}
