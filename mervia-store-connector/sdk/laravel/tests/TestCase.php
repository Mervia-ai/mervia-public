<?php

namespace Mervia\StoreConnector\Tests;

use Mervia\StoreConnector\StoreConnectorServiceProvider;
use Orchestra\Testbench\TestCase as Orchestra;

abstract class TestCase extends Orchestra
{
    protected function getPackageProviders($app): array
    {
        return [StoreConnectorServiceProvider::class];
    }

    protected function defineEnvironment($app): void
    {
        $app['config']->set('cache.default', 'array');
        $app['config']->set('app.key', 'base64:' . base64_encode(str_repeat('k', 32)));
        $app['config']->set('mervia.store_id', 'example-us');
        $app['config']->set('mervia.webhook_url', 'https://hooks.mervia.test/v1/orders');
        $app['config']->set('mervia.webhook_secret', 's3cret-do-not-log');
        $app['config']->set('mervia.include_url', 'https://app.mervia.test/include/v1/sk_example');
        $app['config']->set('mervia.include_key', 'inc_key_123');
        $app['config']->set('mervia.api_key_for_mervia', 'key-current');
        $app['config']->set('mervia.api_key_for_mervia_previous', 'key-previous');
    }
}
