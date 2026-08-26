<?php
/**
 * Uptechify - Razorpay payment configuration
 *
 * Everything you are likely to want to change lives in this file.
 * API keys themselves live in keys.php (see keys.sample.php).
 */

// ---------------------------------------------------------------------------
// 1. API credentials
// ---------------------------------------------------------------------------
$keysFile = __DIR__ . '/keys.php';
$keys = is_readable($keysFile) ? require $keysFile : [];

// Environment variables win over keys.php, so the same code can run on a
// staging box without editing files.
$RZP = [
    'key_id'         => getenv('RAZORPAY_KEY_ID')         ?: ($keys['key_id']         ?? ''),
    'key_secret'     => getenv('RAZORPAY_KEY_SECRET')     ?: ($keys['key_secret']     ?? ''),
    'webhook_secret' => getenv('RAZORPAY_WEBHOOK_SECRET') ?: ($keys['webhook_secret'] ?? ''),
];

// ---------------------------------------------------------------------------
// 2. Business details shown on the Razorpay checkout window
// ---------------------------------------------------------------------------
$BUSINESS = [
    'name'        => 'Uptechify',
    'description' => 'Payment for Uptechify services',
    'logo'        => 'https://uptechify.in/images/logos.png',
    'theme_color' => '#0066FF',
    'currency'    => 'INR',
    'support'     => '+91 99876 65922',
];

// ---------------------------------------------------------------------------
// 3. What customers can pay for
//
// The price here is the ONLY price the server trusts. Whatever the browser
// sends is ignored, so nobody can edit the page and pay Rs 1 for a Rs 25,000
// package. To change a price, change it here.
//
// 'amount' is in RUPEES. Set it to null to let the customer type the amount
// (used for "pay the amount we quoted you" / invoice payments).
// ---------------------------------------------------------------------------
$SERVICES = [
    'web-design'        => ['label' => 'Web Design',             'amount' => null],
    'web-development'   => ['label' => 'Web Development',        'amount' => null],
    'mobile-app'        => ['label' => 'Mobile App Development', 'amount' => null],
    'digital-marketing' => ['label' => 'Digital Marketing',      'amount' => null],
    'seo-smo'           => ['label' => 'SEO / SMO',              'amount' => null],
    'maintenance'       => ['label' => 'Website Maintenance / AMC', 'amount' => null],
    'other'             => ['label' => 'Other / Invoice Payment', 'amount' => null],
];

// Bounds for customer-entered amounts, in rupees. Razorpay's own floor is Rs 1.
$AMOUNT_MIN = 1;
$AMOUNT_MAX = 500000;

// ---------------------------------------------------------------------------
// 4. Where transactions are recorded
//
// Default is one level ABOVE public_html, so the file can never be downloaded
// from the web - it holds customer names, emails and phone numbers.
// If that folder is not writable, the code falls back to api/../data and
// locks it down with .htaccess. See lib.php.
// ---------------------------------------------------------------------------
$DATA_DIR = getenv('UPTECHIFY_DATA_DIR') ?: dirname(__DIR__, 2) . '/uptechify-payments';

// ---------------------------------------------------------------------------
// 5. Pages the customer is sent to
// ---------------------------------------------------------------------------
$PAGES = [
    'success' => '/payment-success.html',
    'failed'  => '/payment-failed.html',
];

// ---------------------------------------------------------------------------
// 6. Abuse protection - max order attempts per IP per hour
// ---------------------------------------------------------------------------
$RATE_LIMIT_PER_HOUR = 20;
