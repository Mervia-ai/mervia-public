<?php

namespace Mervia\StoreConnector\Tests;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use Mervia\StoreConnector\Attribution\Cookie;

class CookieTest extends TestCase
{
    public function test_reads_the_raw_value(): void
    {
        $request = Request::create('/checkout', 'GET', [], ['mervia_attr' => 'v1.9f2c1a7b']);
        $this->assertSame('v1.9f2c1a7b', Cookie::raw($request));
        $this->assertSame('v1.9f2c1a7b', Cookie::forOrder($request));
    }

    public function test_absent_cookie_is_null(): void
    {
        $this->assertNull(Cookie::raw(Request::create('/checkout', 'GET', [], ['other' => 'x'])));
        $this->assertNull(Cookie::raw(Request::create('/checkout', 'GET', [], ['mervia_attr' => ''])));
    }

    public function test_the_header_value_wins_and_is_not_url_decoded(): void
    {
        $request = Request::create('/checkout', 'GET', [], ['mervia_attr' => null]);
        $request->headers->set('Cookie', 'session=abc; mervia_attr=v1.a+b/c%3D=; z=1');
        $this->assertSame('v1.a+b/c%3D=', Cookie::raw($request));
    }

    public function test_survives_the_web_middleware_encrypt_cookies(): void
    {
        Route::middleware('web')->get('/checkout', fn () => ['attr' => Cookie::forOrder()]);

        // As a browser sends it: a plain, unencrypted cookie, also present in the Cookie header.
        // Laravel 11+ keeps it through EncryptCookies::except (registered by the provider);
        // Laravel 10 has no static except, so the raw-header fallback carries it.
        $this->withUnencryptedCookie('mervia_attr', 'v1.77d0e4c2')
            ->withHeader('Cookie', 'mervia_attr=v1.77d0e4c2')
            ->get('/checkout')
            ->assertExactJson(['attr' => 'v1.77d0e4c2']);
    }

    public function test_provider_exempts_the_cookie_from_encryption_where_laravel_allows(): void
    {
        if (!method_exists(\Illuminate\Cookie\Middleware\EncryptCookies::class, 'except')) {
            $this->markTestSkipped('Laravel 10: add mervia_attr to your EncryptCookies $except (see README)');
        }
        Route::middleware('web')->get('/checkout', fn () => ['attr' => Cookie::forOrder()]);

        $this->withUnencryptedCookie('mervia_attr', 'v1.77d0e4c2')
            ->get('/checkout')
            ->assertExactJson(['attr' => 'v1.77d0e4c2']);
    }
}
