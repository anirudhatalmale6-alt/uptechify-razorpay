<?php
/**
 * TEST ONLY - a stand-in for api.razorpay.com so the payment flow can be
 * exercised end to end without touching a real account. Never deployed.
 */

$path   = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$method = $_SERVER['REQUEST_METHOD'];
$body   = json_decode(file_get_contents('php://input') ?: '{}', true) ?: [];

$store = sys_get_temp_dir() . '/mock-rzp.json';
$db    = is_readable($store) ? (json_decode(file_get_contents($store), true) ?: []) : [];

function save(array $db): void
{
    file_put_contents(sys_get_temp_dir() . '/mock-rzp.json', json_encode($db));
}

function out(array $data, int $code = 200): void
{
    http_response_code($code);
    header('Content-Type: application/json');
    echo json_encode($data);
    exit;
}

// POST /orders
if ($method === 'POST' && $path === '/orders') {
    if (!isset($body['amount']) || (int) $body['amount'] < 100) {
        out(['error' => ['code' => 'BAD_REQUEST_ERROR', 'description' => 'amount must be atleast 100']], 400);
    }
    $id = 'order_MOCK' . strtoupper(substr(md5(uniqid('', true)), 0, 10));
    $order = [
        'id'       => $id,
        'entity'   => 'order',
        'amount'   => (int) $body['amount'],
        'currency' => $body['currency'] ?? 'INR',
        'receipt'  => $body['receipt'] ?? '',
        'status'   => 'created',
        'notes'    => $body['notes'] ?? [],
    ];
    $db['orders'][$id] = $order;
    save($db);
    out($order);
}

// POST /_test/pay  - not a Razorpay route; the harness uses it to simulate a
// customer completing (or failing) a payment on Razorpay's side.
if ($method === 'POST' && $path === '/_test/pay') {
    $orderId = $body['order_id'];
    $order   = $db['orders'][$orderId] ?? null;
    if (!$order) {
        out(['error' => ['description' => 'no such order']], 404);
    }
    $paymentId = 'pay_MOCK' . strtoupper(substr(md5(uniqid('', true)), 0, 10));
    $db['payments'][$paymentId] = [
        'id'       => $paymentId,
        'entity'   => 'payment',
        'amount'   => $body['amount'] ?? $order['amount'],
        'currency' => $order['currency'],
        'status'   => $body['status'] ?? 'captured',
        'order_id' => $body['claim_order_id'] ?? $orderId,
        'method'   => $body['method'] ?? 'upi',
        'vpa'      => 'customer@okhdfcbank',
        'email'    => 'test@example.com',
        'contact'  => '+919876543210',
        'fee'      => 236,
        'tax'      => 36,
    ];
    save($db);
    out(['payment_id' => $paymentId]);
}

// GET /payments/{id}
if ($method === 'GET' && preg_match('#^/payments/([^/]+)$#', $path, $m)) {
    $payment = $db['payments'][$m[1]] ?? null;
    if (!$payment) {
        out(['error' => ['code' => 'BAD_REQUEST_ERROR', 'description' => 'The id provided does not exist']], 400);
    }
    out($payment);
}

// POST /payments/{id}/capture
if ($method === 'POST' && preg_match('#^/payments/([^/]+)/capture$#', $path, $m)) {
    $payment = $db['payments'][$m[1]] ?? null;
    if (!$payment) {
        out(['error' => ['description' => 'no such payment']], 400);
    }
    if ((int) $body['amount'] !== (int) $payment['amount']) {
        out(['error' => ['description' => 'capture amount must equal authorised amount']], 400);
    }
    $payment['status'] = 'captured';
    $db['payments'][$m[1]] = $payment;
    save($db);
    out($payment);
}

out(['error' => ['description' => 'mock: unhandled route ' . $method . ' ' . $path]], 404);
