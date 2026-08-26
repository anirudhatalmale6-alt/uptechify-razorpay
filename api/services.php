<?php
/**
 * Feeds the dropdown on payment.html so prices live in exactly one place -
 * config.php. Change a price there and the page follows.
 */

require __DIR__ . '/lib.php';

$out = [];
foreach ($SERVICES as $key => $service) {
    $out[] = [
        'key'    => $key,
        'label'  => $service['label'],
        'amount' => $service['amount'] === null ? null : (float) $service['amount'],
    ];
}

json_out([
    'success'  => true,
    'services' => $out,
    'min'      => $AMOUNT_MIN,
    'max'      => $AMOUNT_MAX,
    'currency' => $BUSINESS['currency'],
    'ready'    => $RZP['key_id'] !== '' && $RZP['key_secret'] !== '',
    'mode'     => str_starts_with($RZP['key_id'], 'rzp_live_') ? 'live' : 'test',
]);
