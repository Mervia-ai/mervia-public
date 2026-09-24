<?php

namespace Mervia\StoreConnector\Content;

use Illuminate\Support\Facades\Blade;

/**
 * @merviaContentHead($product->id)  inside <head>: prints the stored head_html unescaped.
 * @merviaContent($product->id)      where the guide goes: prints the stored body_html unescaped.
 *
 * Both print nothing when nothing is stored for the product, or when the expression itself
 * fails (e.g. $product is null). One lookup per product per request serves both.
 */
final class BladeDirectives
{
    public static function register(): void
    {
        Blade::directive('merviaContentHead', fn (string $expression) => self::compile($expression, 'head'));
        Blade::directive('merviaContent', fn (string $expression) => self::compile($expression, 'body'));
    }

    private static function compile(string $expression, string $method): string
    {
        return "<?php try { echo app(\\Mervia\\StoreConnector\\Content\\ProductContent::class)->{$method}({$expression}); } catch (\\Throwable \$__merviaError) {} ?>";
    }
}
