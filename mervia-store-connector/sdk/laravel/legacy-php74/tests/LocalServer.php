<?php

/**
 * Runs tests/fixtures/server.php on PHP's built-in server so the helpers' real curl code is
 * exercised, timeouts included. The test controls the server through files in $state.
 */
final class LocalServer
{
    public static $base;
    public static $state;
    private static $proc;

    public static function start(): void
    {
        if (self::$proc) {
            return;
        }
        self::$state = sys_get_temp_dir() . '/mervia-state-' . bin2hex(random_bytes(4));
        mkdir(self::$state);
        $port = 20000 + random_int(0, 20000);
        $env = array('PHP_CLI_SERVER_WORKERS' => '4', 'MERVIA_TEST_STATE' => self::$state, 'PATH' => getenv('PATH'));
        self::$proc = proc_open(
            array(PHP_BINARY, '-S', "127.0.0.1:{$port}", __DIR__ . '/fixtures/server.php'),
            array(array('pipe', 'r'), array('file', '/dev/null', 'w'), array('file', '/dev/null', 'w')),
            $pipes, null, $env
        );
        self::$base = "http://127.0.0.1:{$port}";
        for ($i = 0; $i < 100; $i++) {
            $s = @fsockopen('127.0.0.1', $port);
            if ($s) {
                fclose($s);
                register_shutdown_function(function () { proc_terminate(self::$proc); });
                return;
            }
            usleep(50000);
        }
        throw new RuntimeException('built-in server did not start');
    }

    public static function set(string $name, string $value): void
    {
        file_put_contents(self::$state . '/' . $name, $value);
    }

    public static function reset(): void
    {
        foreach (glob(self::$state . '/*') as $f) {
            unlink($f);
        }
    }

    /** @return array[] one decoded line per request the server saw */
    public static function log(string $name): array
    {
        $path = self::$state . '/' . $name . '.log';
        if (!is_file($path)) {
            return array();
        }
        return array_map(function ($l) { return json_decode($l, true); }, array_filter(explode("\n", file_get_contents($path))));
    }
}
