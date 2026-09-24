<?php

namespace Mervia\StoreConnector\Tests;

use Mervia\StoreConnector\Webhook\Signer;
use PHPUnit\Framework\TestCase as PlainTestCase;

class SignerTest extends PlainTestCase
{
    /** HMAC-SHA256('s3cret', '1700000000.{"a":1}'), computed with Python's hmac module. */
    private const VECTOR = '1698a50bc74d1ff1db85c4e0a5297c2ad9fdba245d5737cdb789e4cc6e098940';
    /** HMAC-SHA256('s3cret', '{"a":1}'): the body-only form of contract 1.0.0-draft.1, which no longer verifies. */
    private const BODY_ONLY = '5910e62016ef5034272c926c27071992a465c2335cecf41851bda071577f4f6d';

    public function test_known_vector(): void
    {
        $headers = Signer::sign('{"a":1}', 's3cret', 1700000000);

        $this->assertSame('sha256=' . self::VECTOR, $headers['X-Mervia-Signature']);
        $this->assertSame('sha256=' . hash_hmac('sha256', '1700000000.{"a":1}', 's3cret'), $headers['X-Mervia-Signature']);
        $this->assertSame('1700000000', $headers['X-Mervia-Timestamp']);
    }

    public function test_signs_raw_body_bytes_not_a_reencoding(): void
    {
        $spaced = Signer::sign('{"a": 1}', 's3cret', 1700000000);
        $this->assertNotSame('sha256=' . self::VECTOR, $spaced['X-Mervia-Signature']);
    }

    public function test_signature_binds_the_timestamp(): void
    {
        $later = Signer::sign('{"a":1}', 's3cret', 1700000001);
        $this->assertNotSame('sha256=' . self::VECTOR, $later['X-Mervia-Signature']);
        $this->assertFalse(Signer::verify('{"a":1}', 's3cret', 'sha256=' . self::VECTOR, '1700000001', 1700000001));
    }

    public function test_verify(): void
    {
        $sig = 'sha256=' . self::VECTOR;
        $this->assertTrue(Signer::verify('{"a":1}', 's3cret', $sig, '1700000000', 1700000000));
        $this->assertFalse(Signer::verify('{"a":2}', 's3cret', $sig, '1700000000', 1700000000));
        $this->assertFalse(Signer::verify('{"a":1}', 'other', $sig, '1700000000', 1700000000));
        $this->assertFalse(Signer::verify('{"a":1}', 's3cret', self::VECTOR, '1700000000', 1700000000), 'prefix is required');
        $this->assertFalse(Signer::verify('{"a":1}', 's3cret', strtoupper($sig), '1700000000', 1700000000));
        $this->assertFalse(Signer::verify('{"a":1}', 's3cret', 'sha256=' . self::BODY_ONLY, '1700000000', 1700000000), 'body-only signatures no longer verify');
        $this->assertFalse(Signer::verify('{"a":1}', 's3cret', $sig, 'soon', 1700000000), 'timestamp must be unix seconds');
    }

    public function test_verify_enforces_five_minute_window(): void
    {
        $sig = 'sha256=' . self::VECTOR;
        $this->assertTrue(Signer::verify('{"a":1}', 's3cret', $sig, '1700000000', 1700000300));
        $this->assertFalse(Signer::verify('{"a":1}', 's3cret', $sig, '1700000000', 1700000301));
        $this->assertFalse(Signer::verify('{"a":1}', 's3cret', $sig, '1700000000', 1699999699));
    }
}
