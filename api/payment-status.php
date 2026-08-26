<?php
/**
 * Feeds the thank-you page. Needs both the order id AND the signed token
 * handed out at verification time, so one customer cannot read another's
 * receipt by changing the id in the address bar.
 */

require __DIR__ . '/lib.php';

$orderId = clean_text($_GET['order_id'] ?? '', 60);
$token   = clean_text($_GET['token']    ?? '', 64);

if ($orderId === '' || $token === '') {
    fail('Missing order reference.');
}

if (!hash_equals(receipt_token($orderId), $token)) {
    fail('This receipt link is not valid.', 403);
}

$state = order_state($orderId);
if (!$state) {
    fail('Order not found.', 404);
}

json_out([
    'success'  => true,
    'order_id' => $orderId,
    'status'   => $state['status'] ?? 'unknown',
    'receipt'  => $state['receipt'] ?? '',
    'payment_id' => $state['payment_id'] ?? '',
    'amount'   => (int) ($state['amount'] ?? 0),
    'currency' => $state['currency'] ?? 'INR',
    'service'  => $state['service'] ?? '',
    'name'     => $state['name'] ?? '',
    'email'    => $state['email'] ?? '',
    'method'   => $state['method'] ?? '',
    'at'       => $state['at'] ?? '',
]);
