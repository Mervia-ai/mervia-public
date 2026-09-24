<?php

namespace Mervia\StoreConnector\Include;

use Illuminate\Support\Facades\Blade;

/**
 * @merviaIncludeHead($product->id)  inside <head>: prints head_html (structured data) unescaped.
 * @merviaInclude($product->id)      where the guide goes: prints body_html unescaped.
 *
 * Both render on the server and print nothing when Mervia has nothing for the product, or when
 * the expression itself fails (e.g. $product is null).
 * Fetcher caches per product, so using both directives on one page costs one request at most.
 */
final class BladeDirectives
{
    public static function register(): void
    {
        Blade::directive('merviaIncludeHead', fn (string $expression) => self::compile($expression, 'head_html'));
        Blade::directive('merviaInclude', fn (string $expression) => self::compile($expression, 'body_html'));
    }

    private static function compile(string $expression, string $part): string
    {
        return "<?php try { echo app(\\Mervia\\StoreConnector\\Include\\Fetcher::class)->fetch({$expression})['{$part}']; } catch (\\Throwable \$__merviaError) {} ?>";
    }
}
