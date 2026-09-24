<?php

use PHPUnit\Framework\TestCase;

class MerviaSignerTest extends TestCase
{
    /** HMAC-SHA256('s3cret', '1700000000.{"a":1}'), computed with Python's hmac module. */
    const VECTOR = '1698a50bc74d1ff1db85c4e0a5297c2ad9fdba245d5737cdb789e4cc6e098940';
    /** HMAC-SHA256('s3cret', '{"a":1}'): the body-only form of contract 1.0.0-draft.1, which no longer verifies. */
    const BODY_ONLY = '5910e62016ef5034272c926c27071992a465c2335cecf41851bda071577f4f6d';

    public function test_known_vector(): void
    {
        $h = MerviaSigner::sign('{"a":1}', 's3cret', 1700000000);
        $this->assertSame('sha256=' . self::VECTOR, $h['X-Mervia-Signature']);
        $this->assertSame('sha256=' . hash_hmac('sha256', '1700000000.{"a":1}', 's3cret'), $h['X-Mervia-Signature']);
        $this->assertSame('1700000000', $h['X-Mervia-Timestamp']);
        $this->assertNotSame($h['X-Mervia-Signature'], MerviaSigner::sign('{"a":1}', 's3cret', 1700000001)['X-Mervia-Signature'], 'the timestamp is signed');
    }

    public function test_verify(): void
    {
        $sig = 'sha256=' . self::VECTOR;
        $this->assertTrue(MerviaSigner::verify('{"a":1}', 's3cret', $sig, '1700000000', 1700000000));
        $this->assertFalse(MerviaSigner::verify('{"a": 1}', 's3cret', $sig, '1700000000', 1700000000));
        $this->assertFalse(MerviaSigner::verify('{"a":1}', 'nope', $sig, '1700000000', 1700000000));
        $this->assertFalse(MerviaSigner::verify('{"a":1}', 's3cret', $sig, '1700000001', 1700000001), 'a fresh timestamp breaks the signature');
        $this->assertFalse(MerviaSigner::verify('{"a":1}', 's3cret', 'sha256=' . self::BODY_ONLY, '1700000000', 1700000000), 'body-only no longer verifies');
        $this->assertTrue(MerviaSigner::verify('{"a":1}', 's3cret', $sig, '1700000000', 1700000300));
        $this->assertFalse(MerviaSigner::verify('{"a":1}', 's3cret', $sig, '1700000000', 1700000301));
    }
}
