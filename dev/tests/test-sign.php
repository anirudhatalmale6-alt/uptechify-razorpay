<?php
/**
 * TEST ONLY - stands in for the part Razorpay plays: it takes a payment on the
 * order and hands back a correctly signed response, so the browser flow can be
 * driven end to end. Copied into the site folder only while tests run, then
 * deleted. Never shipped.
 */

require __DIR__ . '/lib.php';

$in = read_input();
$orderId = $in['order_id'] ?? '';

$ch = curl_init((getenv('RAZORPAY_API_BASE') ?: '') . '/_test/pay');
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_POST           => true,
    CURLOPT_HTTPHEADER     => ['Content-Type: application/json'],
    CURLOPT_POSTFIELDS     => json_encode(['order_id' => $orderId]),
]);
$paid = json_decode(curl_exec($ch) ?: '{}', true);
curl_close($ch);

$paymentId = $paid['payment_id'] ?? '';

json_out([
    'razorpay_order_id'   => $orderId,
    'razorpay_payment_id' => $paymentId,
    'razorpay_signature'  => hash_hmac('sha256', $orderId . '|' . $paymentId, $RZP['key_secret']),
]);
