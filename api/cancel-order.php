<?php
/**
 * The customer closed the Razorpay window without paying, or the checkout
 * reported a failure. Record it so an abandoned attempt is distinguishable
 * from a failed one when you look at the log.
 *
 * This only ever moves an order OUT of "created". It can never mark something
 * unpaid that a verified payment or a webhook has already marked paid.
 */

require __DIR__ . '/lib.php';

require_post();

$in = read_input();

$orderId = clean_text($in['order_id'] ?? '', 60);
$reason  = clean_text($in['reason']   ?? '', 200);
$outcome = ($in['outcome'] ?? '') === 'failed' ? 'failed' : 'cancelled';

if ($orderId === '') {
    fail('Missing order id.');
}

$known = order_state($orderId);
if (!$known) {
    fail('Unknown order.', 404);
}

if (in_array($known['status'] ?? '', ['paid', 'refunded'], true)) {
    // Already settled - leave it alone.
    json_out(['success' => true, 'status' => $known['status']]);
}

record_event([
    'event'    => $outcome === 'failed' ? 'payment_failed' : 'payment_cancelled',
    'order_id' => $orderId,
    'status'   => $outcome,
    'reason'   => $reason !== '' ? $reason : ($outcome === 'failed' ? 'Payment failed at the bank' : 'Customer closed the payment window'),
]);

json_out(['success' => true, 'status' => $outcome]);
