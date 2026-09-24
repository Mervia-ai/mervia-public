<?php

namespace Mervia\StoreConnector;

use Illuminate\Cookie\Middleware\EncryptCookies;
use Illuminate\Support\ServiceProvider;
use Mervia\StoreConnector\Attribution\Cookie;
use Mervia\StoreConnector\Content\BladeDirectives as ContentDirectives;
use Mervia\StoreConnector\Content\DatabaseProductContentStore;
use Mervia\StoreConnector\Content\ProductContent;
use Mervia\StoreConnector\Content\ProductContentStore;
use Mervia\StoreConnector\Http\Middleware\AuthenticateMervia;
use Mervia\StoreConnector\Include\BladeDirectives as IncludeDirectives;
use Mervia\StoreConnector\Include\Fetcher;

class StoreConnectorServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->mergeConfigFrom(__DIR__ . '/config/mervia.php', 'mervia');
        $this->app->singleton(ProductContent::class);
        $this->app->bind(ProductContentStore::class, DatabaseProductContentStore::class);
        $this->app->singleton(Fetcher::class);
    }

    public function boot(): void
    {
        $this->publishes([__DIR__ . '/config/mervia.php' => config_path('mervia.php')], 'mervia-config');
        $this->publishes([__DIR__ . '/database/migrations' => database_path('migrations')], 'mervia-migrations');
        $this->loadMigrationsFrom(__DIR__ . '/database/migrations');

        ContentDirectives::register();
        IncludeDirectives::register();

        $this->app['router']->aliasMiddleware('mervia.auth', AuthenticateMervia::class);

        if (method_exists(EncryptCookies::class, 'except')) {
            EncryptCookies::except([Cookie::NAME]);
        }
    }
}
