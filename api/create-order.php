<?php
/**
 * Step 1 of the payment: create a Razorpay order.
 *
 * The browser sends who is paying and what for. The AMOUNT is decided here,
 * on the server, from config.php - never taken from the browser unless that
 * service is explicitly set up as customer-entered.
 */

require __DIR__ . '/lib.php';

require_post();

$in = read_input();

// Honeypot - a real customer never fills a hidden field.
if (clean_text($in['company_website'] ?? '', 200) !== '') {
    fail('Request rejected.', 422);
}

if (!rate_limit_ok()) {
    fail('Too many payment attempts from this connection. Please wait a few minutes and try again.', 429);
}

// --- customer details -------------------------------------------------------
$name    = clean_text($in['name']    ?? '', 100);
$email   = clean_text($in['email']   ?? '', 120);
$phone   = clean_phone($in['phone']  ?? '');
$notes   = clean_text($in['notes']   ?? '', 300);
$invoice = clean_text($in['invoice'] ?? '', 60);
$serviceKey = clean_text($in['service'] ?? '', 60);

if ($name === '' || mb_strlen($name) < 2) {
    fail('Please enter your name.');
}
if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    fail('Please enter a valid email address.');
}
if (!preg_match('/^\+?[0-9]{10,14}$/', $phone)) {
    fail('Please enter a valid phone number (10 digits, or with country code).');
}
if (!isset($SERVICES[$serviceKey])) {
    fail('Please choose what the payment is for.');
}

$service = $SERVICES[$serviceKey];

// --- amount, decided server side -------------------------------------------
if ($service['amount'] !== null) {
    // Fixed price package. The browser's number is ignored on purpose.
    $rupees = (float) $service['amount'];
} else {
    $rupees = is_numeric($in['amount'] ?? null) ? (float) $in['amount'] : 0.0;
    if ($rupees < $AMOUNT_MIN || $rupees > $AMOUNT_MAX) {
        fail(sprintf(
            'Please enter an amount between Rs %s and Rs %s.',
            number_format($AMOUNT_MIN),
            number_format($AMOUNT_MAX)
        ));
    }
}

// Razorpay works in paise. Round to the nearest paisa so 1999.999 can never
// become a fraction Razorpay rejects.
$paise = (int) round($rupees * 100);
if ($paise < 100) {
    fail('The minimum online payment is Rs 1.');
}

// --- create the order -------------------------------------------------------
$receipt = 'UPT' . date('ymdHis') . strtoupper(substr(bin2hex(random_bytes(3)), 0, 4));

[$status, $order] = rzp_call('POST', '/orders', [
    'amount'   => $paise,
    'currency' => $BUSINESS['currency'],
    'receipt'  => $receipt,
    'notes'    => array_filter([
        'customer_name'  => $name,
        'customer_email' => $email,
        'customer_phone' => $phone,
        'service'        => $service['label'],
        'invoice_ref'    => $invoice,
        'customer_notes' => $notes,
    ]),
]);

if ($status !== 200 || empty($order['id'])) {
    error_log('[razorpay] order creation failed: ' . json_encode($order));
    record_event([
        'event'   => 'order_failed',
        'receipt' => $receipt,
        'amount'  => $paise,
        'status'  => 'error',
        'email'   => $email,
        'reason'  => rzp_error_text($order, 'unknown error'),
        'ip'      => client_ip(),
    ]);
    fail(rzp_error_text($order, 'Could not start the payment. Please try again in a moment.'), 502);
}

record_event([
    'event'    => 'order_created',
    'order_id' => $order['id'],
    'receipt'  => $receipt,
    'amount'   => $paise,
    'currency' => $BUSINESS['currency'],
    'status'   => 'created',
    'name'     => $name,
    'email'    => $email,
    'phone'    => $phone,
    'service'  => $service['label'],
    'invoice'  => $invoice,
    'notes'    => $notes,
    'ip'       => client_ip(),
]);

json_out([
    'success'  => true,
    'key_id'   => $RZP['key_id'],          // publishable, safe in the browser
    'order_id' => $order['id'],
    'amount'   => $paise,
    'currency' => $BUSINESS['currency'],
    'receipt'  => $receipt,
    'business' => [
        'name'        => $BUSINESS['name'],
        'description' => $service['label'] . ' - ' . $BUSINESS['name'],
        'logo'        => $BUSINESS['logo'],
        'theme_color' => $BUSINESS['theme_color'],
    ],
    'prefill'  => ['name' => $name, 'email' => $email, 'contact' => $phone],
]);
