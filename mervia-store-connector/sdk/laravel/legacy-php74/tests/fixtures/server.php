<?php
// Router for `php -S`: a fake Mervia include endpoint and webhook receiver, steered by files in MERVIA_TEST_STATE.
$state = getenv('MERVIA_TEST_STATE');
$get = function ($name, $default) use ($state) {
    $v = @file_get_contents("{$state}/{$name}");
    return $v === false ? $default : $v;
};
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

if (preg_match('#^/include/v1/sk/products/(.+)$#', $path, $m)) {
    $inm = isset($_SERVER['HTTP_IF_NONE_MATCH']) ? $_SERVER['HTTP_IF_NONE_MATCH'] : '';
    $line = array('raw_id' => $m[1], 'auth' => isset($_SERVER['HTTP_AUTHORIZATION']) ? $_SERVER['HTTP_AUTHORIZATION'] : '', 'inm' => $inm);
    file_put_contents("{$state}/include.log", json_encode($line) . "\n", FILE_APPEND | LOCK_EX);
    $mode = $get('mode', 'ok');
    if ($mode === 'slow') {
        usleep(1500000); // past the client's 1 s timeout; kept short because the built-in server
                         // can queue the next connection behind this worker
    }
    if ($mode === 'gone') {
        http_response_code(404);
        echo '{"error":"not_found"}';
        return true;
    }
    if ($mode === 'boom') {
        http_response_code(500);
        return true;
    }
    $v = $get('version', '1');
    header("ETag: \"v{$v}\"");
    if ($inm === "\"v{$v}\"") {
        http_response_code(304);
        return true;
    }
    header('Content-Type: application/json');
    echo json_encode(array(
        'version' => (int) $v,
        'head_html' => "<script type=\"application/ld+json\" id=\"mervia-product-schema\">{\"v\":{$v}}</script>",
        'body_html' => "<section id=\"mervia-shopping-guide\">v{$v} &amp; more</section>",
    ));
    return true;
}

if ($path === '/webhook') {
    $line = array(
        'sig' => isset($_SERVER['HTTP_X_MERVIA_SIGNATURE']) ? $_SERVER['HTTP_X_MERVIA_SIGNATURE'] : '',
        'ts' => isset($_SERVER['HTTP_X_MERVIA_TIMESTAMP']) ? $_SERVER['HTTP_X_MERVIA_TIMESTAMP'] : '',
        'ct' => isset($_SERVER['CONTENT_TYPE']) ? $_SERVER['CONTENT_TYPE'] : '',
        'body' => file_get_contents('php://input'),
    );
    file_put_contents("{$state}/webhook.log", json_encode($line) . "\n", FILE_APPEND | LOCK_EX);
    http_response_code((int) $get('webhook_status', '200'));
    return true;
}

http_response_code(404);
return true;
