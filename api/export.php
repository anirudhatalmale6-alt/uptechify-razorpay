<?php
/**
 * Downloads the transaction log as a CSV you can open in Excel.
 *
 *   https://uptechify.in/api/export.php?token=YOUR_REPORT_TOKEN
 *
 * Set 'report_token' in keys.php to a long random string. Without it this
 * endpoint stays switched off - it will never serve customer data by default.
 */

require __DIR__ . '/lib.php';

$keysFile = __DIR__ . '/keys.php';
$keys     = is_readable($keysFile) ? require $keysFile : [];
$expected = getenv('UPTECHIFY_REPORT_TOKEN') ?: ($keys['report_token'] ?? '');

if ($expected === '') {
    fail('Export is switched off. Set report_token in keys.php to enable it.', 403);
}

$given = (string) ($_GET['token'] ?? '');
if (!hash_equals($expected, $given)) {
    // Same message either way, so this cannot be used to probe for the token.
    fail('Not authorised.', 403);
}

$file = ledger_path();
if (!is_readable($file)) {
    fail('No transactions recorded yet.', 404);
}

// Replay the log so each order appears once, in its final state.
$orders = [];
$fh = fopen($file, 'rb');
while (($line = fgets($fh)) !== false) {
    $row = json_decode($line, true);
    if (!is_array($row) || empty($row['order_id'])) {
        continue;
    }
    $id = $row['order_id'];
    $orders[$id] = isset($orders[$id]) ? array_merge($orders[$id], $row) : $row;
}
fclose($fh);

header('Content-Type: text/csv; charset=utf-8');
header('Content-Disposition: attachment; filename="uptechify-payments-' . gmdate('Y-m-d') . '.csv"');
header('Cache-Control: no-store');

$out = fopen('php://output', 'w');
fputcsv($out, [
    'Date (UTC)', 'Status', 'Receipt', 'Order ID', 'Payment ID',
    'Amount (INR)', 'Service', 'Invoice Ref', 'Name', 'Email', 'Phone', 'Method', 'Note',
]);

foreach ($orders as $order) {
    fputcsv($out, [
        $order['at']         ?? '',
        $order['status']     ?? '',
        $order['receipt']    ?? '',
        $order['order_id']   ?? '',
        $order['payment_id'] ?? '',
        number_format(($order['amount'] ?? 0) / 100, 2, '.', ''),
        $order['service']    ?? '',
        $order['invoice']    ?? '',
        $order['name']       ?? '',
        $order['email']      ?? '',
        $order['phone']      ?? '',
        $order['method']     ?? '',
        $order['notes']      ?? '',
    ]);
}
fclose($out);
