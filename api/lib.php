<?php
/**
 * Shared helpers for the Uptechify Razorpay integration.
 */

require __DIR__ . '/config.php';

// ---------------------------------------------------------------------------
// Responses
// ---------------------------------------------------------------------------

function json_out(array $payload, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES);
    exit;
}

function fail(string $message, int $status = 400, array $extra = []): void
{
    json_out(array_merge(['success' => false, 'error' => $message], $extra), $status);
}

/** Reads a JSON request body, falling back to normal form posts. */
function read_input(): array
{
    $raw = file_get_contents('php://input');
    if ($raw !== false && $raw !== '') {
        $decoded = json_decode($raw, true);
        if (is_array($decoded)) {
            return $decoded;
        }
    }
    return $_POST;
}

function require_post(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
        fail('Method not allowed.', 405);
    }
}

// ---------------------------------------------------------------------------
// Storage
//
// One JSON object per line. Small, human readable, survives concurrent writes
// because each append is a single locked write.
// ---------------------------------------------------------------------------

/**
 * Returns [directory, isInsideWebroot].
 *
 * First choice is the folder above public_html, which the web server cannot
 * serve at all. If that is not writable we fall back to a folder next to the
 * API - see ledger_path() for how that file is made unreadable over HTTP.
 */
function data_dir(bool &$fallback = null): string
{
    global $DATA_DIR;

    $fallback = false;
    $dir = $DATA_DIR;
    if (!is_dir($dir)) {
        @mkdir($dir, 0750, true);
    }

    if (is_dir($dir) && is_writable($dir)) {
        return $dir;
    }

    $fallback = true;
    $dir = dirname(__DIR__) . '/data';
    if (!is_dir($dir)) {
        @mkdir($dir, 0750, true);
    }
    $guard = $dir . '/.htaccess';
    if (!file_exists($guard)) {
        @file_put_contents($guard, "Require all denied\n<IfModule !mod_authz_core.c>\nDeny from all\n</IfModule>\n");
    }
    if (!file_exists($dir . '/index.html')) {
        @file_put_contents($dir . '/index.html', '');
    }

    return $dir;
}

/**
 * Inside the webroot the ledger is a .php file whose first line is an exit.
 * Anyone who requests it gets an empty page even if .htaccess is ignored -
 * the file cannot be read out, only executed, and executing it does nothing.
 * The readers below skip that first line because it is not valid JSON.
 */
function ledger_path(): string
{
    $inside = false;
    $dir = data_dir($inside);

    if (!$inside) {
        return $dir . '/transactions.jsonl';
    }

    $path = $dir . '/transactions.php';
    if (!file_exists($path)) {
        @file_put_contents($path, "<?php http_response_code(404); exit; ?>\n");
    }
    return $path;
}

function log_line(string $file, array $row): void
{
    $fh = @fopen($file, 'ab');
    if (!$fh) {
        error_log('[razorpay] cannot write ' . $file);
        return;
    }
    @flock($fh, LOCK_EX);
    @fwrite($fh, json_encode($row, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n");
    @flock($fh, LOCK_UN);
    @fclose($fh);
}

function record_event(array $row): void
{
    $row['at'] = gmdate('c');
    log_line(ledger_path(), $row);
}

/**
 * Replays the ledger to get the current state of one order.
 * Later lines overwrite earlier ones, so the last word wins.
 */
function order_state(string $orderId): ?array
{
    $file = ledger_path();
    if (!is_readable($file)) {
        return null;
    }
    $state = null;
    $fh = fopen($file, 'rb');
    while (($line = fgets($fh)) !== false) {
        $row = json_decode($line, true);
        if (is_array($row) && ($row['order_id'] ?? null) === $orderId) {
            $state = $state === null ? $row : array_merge($state, $row);
        }
    }
    fclose($fh);
    return $state;
}

// ---------------------------------------------------------------------------
// Razorpay REST API
// ---------------------------------------------------------------------------

function rzp_call(string $method, string $path, ?array $body = null): array
{
    global $RZP;

    if ($RZP['key_id'] === '' || $RZP['key_secret'] === '') {
        return [0, ['error' => ['description' => 'Razorpay keys are not configured on the server.']]];
    }

    // Overridable so the flow can be exercised against a stub during testing.
    // Left unset, it is always the real Razorpay API.
    $base = getenv('RAZORPAY_API_BASE') ?: 'https://api.razorpay.com/v1';

    $ch = curl_init($base . $path);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CUSTOMREQUEST  => $method,
        CURLOPT_USERPWD        => $RZP['key_id'] . ':' . $RZP['key_secret'],
        CURLOPT_HTTPHEADER     => ['Content-Type: application/json'],
        CURLOPT_TIMEOUT        => 30,
        CURLOPT_CONNECTTIMEOUT => 10,
    ]);
    if ($body !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body, JSON_UNESCAPED_SLASHES));
    }

    $response = curl_exec($ch);
    $status   = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $curlErr  = curl_error($ch);
    curl_close($ch);

    if ($response === false) {
        return [0, ['error' => ['description' => 'Could not reach Razorpay: ' . $curlErr]]];
    }

    $decoded = json_decode($response, true);
    return [$status, is_array($decoded) ? $decoded : ['raw' => $response]];
}

/** Razorpay's error payloads are nested; pull out something printable. */
function rzp_error_text(array $decoded, string $fallback): string
{
    return $decoded['error']['description'] ?? ($decoded['description'] ?? $fallback);
}

/**
 * A short signed token so the thank-you page can show the receipt for ONE
 * order only. Without it, anyone could read back any order by guessing ids.
 */
function receipt_token(string $orderId): string
{
    global $RZP;
    return substr(hash_hmac('sha256', 'receipt:' . $orderId, $RZP['key_secret']), 0, 32);
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

function clean_text($value, int $max): string
{
    $value = is_scalar($value) ? (string) $value : '';
    $value = strip_tags(trim($value));
    // Strip control characters so nothing odd lands in the ledger or in
    // Razorpay's notes field.
    $value = preg_replace('/[\x00-\x1F\x7F]/u', '', $value);
    return mb_substr($value, 0, $max);
}

function clean_phone($value): string
{
    $digits = preg_replace('/[^0-9+]/', '', (string) $value);
    return mb_substr($digits, 0, 15);
}

function client_ip(): string
{
    return $_SERVER['REMOTE_ADDR'] ?? '0.0.0.0';
}

/** Simple per-IP throttle so the order endpoint cannot be hammered. */
function rate_limit_ok(): bool
{
    global $RATE_LIMIT_PER_HOUR;

    $inside = false;
    $dir    = data_dir($inside);
    // Same trick as the ledger: a .php file that exits, so the IP list is not
    // downloadable if this ever sits inside the webroot.
    $prefix = $inside ? "<?php http_response_code(404); exit; ?>\n" : '';
    $file   = $dir . ($inside ? '/ratelimit.php' : '/ratelimit.json');
    $now    = time();
    $ip     = client_ip();

    $fh = @fopen($file, 'c+b');
    if (!$fh) {
        return true; // never block a real customer because of a disk problem
    }
    @flock($fh, LOCK_EX);
    $contents = stream_get_contents($fh) ?: '';
    $brace    = strpos($contents, '{');
    $buckets  = $brace === false ? null : json_decode(substr($contents, $brace), true);
    $buckets  = is_array($buckets) ? $buckets : [];

    foreach ($buckets as $key => $stamps) {
        $buckets[$key] = array_values(array_filter($stamps, fn($t) => $t > $now - 3600));
        if (!$buckets[$key]) {
            unset($buckets[$key]);
        }
    }

    $mine    = $buckets[$ip] ?? [];
    $allowed = count($mine) < $RATE_LIMIT_PER_HOUR;
    if ($allowed) {
        $mine[]       = $now;
        $buckets[$ip] = $mine;
    }

    ftruncate($fh, 0);
    rewind($fh);
    fwrite($fh, $prefix . json_encode($buckets));
    @flock($fh, LOCK_UN);
    fclose($fh);

    return $allowed;
}
