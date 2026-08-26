# Razorpay Payment Gateway - uptechify.in

Razorpay checkout for the Uptechify website. Plain PHP endpoints alongside the
existing static pages - no framework, no database, no Composer.

Full setup, testing and day-to-day instructions: **[RAZORPAY-SETUP.md](RAZORPAY-SETUP.md)**

## What goes on the server

Copy everything except `dev/` into `public_html`:

- `payment.html` - the Pay Now page
- `payment-success.html` - receipt
- `payment-failed.html` - not completed
- `api/` - the server side

Then copy `api/keys.sample.php` to `api/keys.php` and paste your Razorpay keys in.

## How a payment goes through

1. `create-order.php` works out the amount **on the server** from `config.php`
   and opens a Razorpay order.
2. The customer pays in the Razorpay window.
3. `verify-payment.php` checks the HMAC-SHA256 signature, then asks Razorpay's
   API what the payment really was, and refuses it if the amount or order does
   not match.
4. `webhook.php` records the payment independently, so closing the browser
   mid-payment cannot lose it.

Cancelled and failed attempts are recorded separately from successful ones.
The transaction log is written above `public_html` so it cannot be downloaded.

## Tests

```
python3 dev/tests/run-tests.py      # 71 checks - API, signatures, webhook, storage
python3 dev/tests/browser-test.py   # 30 checks - real browser, desktop and phone
```

Both run against a stand-in for the Razorpay API (`dev/tests/mock-razorpay/`),
so no real account and no real money is involved. `dev/assemble.py` rebuilds the
three HTML pages from the live site's header and footer.
