<?php

use PHPUnit\Framework\TestCase;

class MerviaAttributionCookieTest extends TestCase
{
    public function test_reads_the_raw_value_or_null(): void
    {
        $this->assertSame('v1.9f2c1a7b', MerviaAttributionCookie::forOrder(array('mervia_attr' => 'v1.9f2c1a7b')));
        $this->assertNull(MerviaAttributionCookie::raw(array('other' => 'x')));
        $this->assertNull(MerviaAttributionCookie::raw(array('mervia_attr' => '')));
        $this->assertNull(MerviaAttributionCookie::raw(array('mervia_attr' => array('x'))));
    }

    public function test_reads_the_cookie_header_verbatim_first(): void
    {
        $_SERVER['HTTP_COOKIE'] = 'session=abc; mervia_attr=v1.a+b/c%3D=; z=1';
        $_COOKIE['mervia_attr'] = 'v1.a b/c==';   // what PHP's decoding would give
        $this->assertSame('v1.a+b/c%3D=', MerviaAttributionCookie::raw());
        unset($_SERVER['HTTP_COOKIE'], $_COOKIE['mervia_attr']);
    }

    public function test_defaults_to_the_superglobal(): void
    {
        $_COOKIE['mervia_attr'] = 'v1.77d0e4c2';
        $this->assertSame('v1.77d0e4c2', MerviaAttributionCookie::raw());
        unset($_COOKIE['mervia_attr']);
        $this->assertNull(MerviaAttributionCookie::raw());
    }
}
