<?php
/**
 * Razorpay API credentials for uptechify.in
 *
 * 1. Copy this file to  keys.php  (same folder).
 * 2. Paste your keys in below.
 * 3. Never commit keys.php anywhere public - it holds your secret.
 *
 * Test keys start with  rzp_test_  ... use these while checking the flow.
 * Live keys start with  rzp_live_  ... switch to these when you go live.
 */

return [
    // Razorpay Dashboard -> Account & Settings -> API Keys
    'key_id'         => 'rzp_test_XXXXXXXXXXXXXX',
    'key_secret'     => 'XXXXXXXXXXXXXXXXXXXXXXXX',

    // Razorpay Dashboard -> Account & Settings -> Webhooks -> (your webhook) -> Secret
    // Leave blank until you create the webhook.
    'webhook_secret' => '',

    // Long random string of your choosing. It unlocks the CSV download at
    // /api/export.php?token=... Leave it blank and that download stays off.
    'report_token'   => '',
];
