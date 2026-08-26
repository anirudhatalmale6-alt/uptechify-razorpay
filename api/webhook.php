<?php
/**
 * Razorpay webhook receiver.
 *
 * Why this matters: if a customer pays and then closes the tab before the
 * browser can call verify-payment.php, the money is collected but your site
 * would never hear about it. Razorpay calls this URL server to server, so the
 * payment is recorded either way.
 *
 * Set it up at: Razorpay Dashboard -> Account & Settings -> Webhooks
 *   URL     https://uptechify.in/api/webhook.php
 *   Events  payment.captured, payment.failed, order.paid, refund.processed
 *   Secret  anything you like - paste the same string into keys.php
 */

require __DIR__ . '/lib.php';

$raw = file_get_contents('php://input') ?: '';
$signature = $_SERVER['HTTP_X_RAZORPAY_SIGNATURE'] ?? '';

if ($RZP['webhook_secret'] === '') {
    error_log('[razorpay] webhook received but no webhook secret is configured');
    http_response_code(500);
    exit;
}

$expected = hash_hmac('sha256', $raw, $RZP['webhook_secret']);

if ($signature === '' || !hash_equals($expected, $signature)) {
    error_log('[razorpay] webhook signature rejected from ' . client_ip());
    http_response_code(400);
    exit;
}

$body = json_decode($raw, true);
if (!is_array($body)) {
    http_response_code(400);
    exit;
}

$event   = $body['event'] ?? '';
$payment = $body['payload']['payment']['entity'] ?? [];
$refund  = $body['payload']['refund']['entity']  ?? [];
$order   = $body['payload']['order']['entity']   ?? [];

$orderId = $payment['order_id'] ?? ($refund['payment_id'] ?? '') ?: ($order['id'] ?? '');
if ($orderId === '' && !empty($payment['order_id'])) {
    $orderId = $payment['order_id'];
}

switch ($event) {
    case 'payment.captured':
        $known = order_state($payment['order_id'] ?? '');
        // Guard: never accept a captured amount that differs from what we asked for.
        if ($known && (int) $known['amount'] !== (int) ($payment['amount'] ?? 0)) {
            record_event([
                'event'      => 'webhook_amount_mismatch',
                'order_id'   => $payment['order_id'] ?? '',
                'payment_id' => $payment['id'] ?? '',
                'status'     => 'invalid',
                'expected'   => (int) $known['amount'],
                'received'   => (int) ($payment['amount'] ?? 0),
            ]);
            break;
        }
        record_event([
            'event'      => 'webhook_captured',
            'order_id'   => $payment['order_id'] ?? '',
            'payment_id' => $payment['id'] ?? '',
            'status'     => 'paid',
            'amount'     => (int) ($payment['amount'] ?? 0),
            'method'     => $payment['method'] ?? '',
            'email'      => $payment['email'] ?? '',
            'contact'    => $payment['contact'] ?? '',
            'fee'        => (int) ($payment['fee'] ?? 0),
        ]);
        break;

    case 'payment.failed':
        $known = order_state($payment['order_id'] ?? '');
        if (($known['status'] ?? '') !== 'paid') {
            record_event([
                'event'      => 'webhook_failed',
                'order_id'   => $payment['order_id'] ?? '',
                'payment_id' => $payment['id'] ?? '',
                'status'     => 'failed',
                'amount'     => (int) ($payment['amount'] ?? 0),
                'method'     => $payment['method'] ?? '',
                'reason'     => $payment['error_description'] ?? ($payment['error_reason'] ?? 'declined'),
            ]);
        }
        break;

    case 'order.paid':
        record_event([
            'event'    => 'webhook_order_paid',
            'order_id' => $order['id'] ?? '',
            'status'   => 'paid',
            'amount'   => (int) ($order['amount_paid'] ?? 0),
        ]);
        break;

    case 'refund.processed':
    case 'refund.created':
        record_event([
            'event'      => 'webhook_refund',
            'order_id'   => $refund['notes']['order_id'] ?? ($payment['order_id'] ?? ''),
            'payment_id' => $refund['payment_id'] ?? '',
            'refund_id'  => $refund['id'] ?? '',
            'status'     => 'refunded',
            'amount'     => (int) ($refund['amount'] ?? 0),
        ]);
        break;

    default:
        record_event(['event' => 'webhook_other', 'razorpay_event' => $event, 'order_id' => $orderId]);
}

// Razorpay retries anything that is not a 2xx, so always answer 200 once the
// event has been written down.
http_response_code(200);
header('Content-Type: application/json');
echo json_encode(['received' => true]);
