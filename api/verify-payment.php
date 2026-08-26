<?php
/**
 * Step 2: verify the payment before anyone is shown a success screen.
 *
 * Three checks, in this order:
 *   1. The signature Razorpay sent back matches HMAC-SHA256(order_id|payment_id)
 *      using our key secret. This is what proves the response really came from
 *      Razorpay and was not typed into the browser console.
 *   2. We ask Razorpay's API directly what that payment looks like.
 *   3. The amount and order id on the payment match the order we created.
 *
 * Only then is the payment marked paid.
 */

require __DIR__ . '/lib.php';

require_post();

$in = read_input();

$orderId   = clean_text($in['razorpay_order_id']   ?? '', 60);
$paymentId = clean_text($in['razorpay_payment_id'] ?? '', 60);
$signature = clean_text($in['razorpay_signature']  ?? '', 200);

if ($orderId === '' || $paymentId === '' || $signature === '') {
    fail('Incomplete payment response.');
}

// --- 1. signature -----------------------------------------------------------
$expected = hash_hmac('sha256', $orderId . '|' . $paymentId, $RZP['key_secret']);

if (!hash_equals($expected, $signature)) {
    record_event([
        'event'      => 'signature_mismatch',
        'order_id'   => $orderId,
        'payment_id' => $paymentId,
        'status'     => 'invalid',
        'ip'         => client_ip(),
    ]);
    error_log("[razorpay] signature mismatch for order $orderId payment $paymentId");
    fail('Payment verification failed. If money has left your account, contact us and we will sort it out - nothing is lost.', 400);
}

// --- 2. ask Razorpay what really happened ------------------------------------
[$status, $payment] = rzp_call('GET', '/payments/' . rawurlencode($paymentId));

if ($status !== 200 || empty($payment['id'])) {
    // The signature was good, so the payment is almost certainly fine - we just
    // could not read it back. The webhook will settle it. Do not fail the
    // customer over this.
    record_event([
        'event'      => 'verify_lookup_failed',
        'order_id'   => $orderId,
        'payment_id' => $paymentId,
        'status'     => 'pending_confirmation',
        'reason'     => rzp_error_text($payment, 'lookup failed'),
    ]);
    json_out([
        'success'  => true,
        'pending'  => true,
        'order_id' => $orderId,
        'token'    => receipt_token($orderId),
        'message'  => 'Payment received. We are confirming it with the bank.',
    ]);
}

// --- 3. does it match the order we created? ----------------------------------
$known = order_state($orderId);

if (($payment['order_id'] ?? '') !== $orderId) {
    record_event([
        'event'      => 'order_mismatch',
        'order_id'   => $orderId,
        'payment_id' => $paymentId,
        'status'     => 'invalid',
    ]);
    fail('Payment verification failed.', 400);
}

if ($known && (int) $payment['amount'] !== (int) $known['amount']) {
    record_event([
        'event'      => 'amount_mismatch',
        'order_id'   => $orderId,
        'payment_id' => $paymentId,
        'status'     => 'invalid',
        'expected'   => (int) $known['amount'],
        'received'   => (int) $payment['amount'],
    ]);
    fail('Payment verification failed.', 400);
}

// Some accounts authorise first and capture later. If this one did, capture it
// now so the money is actually collected rather than sitting on hold.
if (($payment['status'] ?? '') === 'authorized') {
    [$capStatus, $captured] = rzp_call('POST', '/payments/' . rawurlencode($paymentId) . '/capture', [
        'amount'   => (int) $payment['amount'],
        'currency' => $payment['currency'] ?? $BUSINESS['currency'],
    ]);
    if ($capStatus === 200 && !empty($captured['id'])) {
        $payment = $captured;
    } else {
        error_log('[razorpay] capture failed for ' . $paymentId . ': ' . json_encode($captured));
    }
}

$paid = in_array($payment['status'] ?? '', ['captured', 'authorized'], true);

record_event([
    'event'      => 'payment_verified',
    'order_id'   => $orderId,
    'payment_id' => $paymentId,
    'status'     => $paid ? 'paid' : ($payment['status'] ?? 'unknown'),
    'amount'     => (int) ($payment['amount'] ?? 0),
    'method'     => $payment['method'] ?? '',
    'bank'       => $payment['bank'] ?? ($payment['wallet'] ?? ($payment['vpa'] ?? '')),
    'fee'        => (int) ($payment['fee'] ?? 0),
    'tax'        => (int) ($payment['tax'] ?? 0),
    'email'      => $payment['email'] ?? '',
    'contact'    => $payment['contact'] ?? '',
]);

if (!$paid) {
    fail('The bank did not complete this payment. Nothing has been charged.', 402, [
        'order_id' => $orderId,
        'reason'   => $payment['error_description'] ?? ($payment['status'] ?? 'not captured'),
    ]);
}

json_out([
    'success'    => true,
    'order_id'   => $orderId,
    'payment_id' => $paymentId,
    'token'      => receipt_token($orderId),
    'message'    => 'Payment successful.',
]);
