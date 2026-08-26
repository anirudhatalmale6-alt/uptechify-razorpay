# Razorpay Payments for uptechify.in

Everything here drops into your existing site. No framework, no database, no
Composer - just PHP files next to the HTML pages you already have.

---

## 1. What gets added

```
public_html/
  payment.html            <- the Pay Now page
  payment-success.html    <- receipt / thank you
  payment-failed.html     <- payment did not go through
  api/
    config.php            <- prices, business details, settings
    keys.php              <- YOUR API KEYS (you create this, see step 3)
    keys.sample.php       <- template to copy
    lib.php               <- shared code
    services.php          <- feeds the dropdown on the payment page
    create-order.php      <- starts a payment
    verify-payment.php    <- checks the payment is genuine
    cancel-order.php      <- records cancelled / failed attempts
    payment-status.php    <- feeds the receipt page
    webhook.php           <- Razorpay calls this server to server
    export.php            <- downloads your transactions as CSV
```

One folder is also created **above** `public_html`, called
`uptechify-payments/`. That is where the transaction log is written. It sits
outside the website on purpose - it holds customer names, emails and phone
numbers, and nothing outside the website can be downloaded by anyone.

---

## 2. Upload

Upload the files above into `public_html`, keeping the `api` folder structure.
Nothing existing is overwritten - every file is new.

---

## 3. Put your keys in

1. In `api/`, copy `keys.sample.php` to `keys.php`.
2. Open it and paste in your keys:

   - Razorpay Dashboard -> **Account & Settings** -> **API Keys**
   - Keep the dashboard toggle on **Test Mode** for now. Test keys start with
     `rzp_test_`.

3. Save. That is the whole configuration.

`keys.php` is the only file holding your secret. Do not email it, and do not
put it anywhere public.

---

## 4. Add the webhook

This is what protects you when a customer pays and then closes the browser
before the page can finish. Razorpay tells your server directly, so the payment
is still recorded.

- Razorpay Dashboard -> **Account & Settings** -> **Webhooks** -> **Add New Webhook**
- **URL:** `https://uptechify.in/api/webhook.php`
- **Secret:** make up a long random string
- **Active Events:** `payment.captured`, `payment.failed`, `order.paid`,
  `refund.processed`
- Save, then paste that same secret into `webhook_secret` in `keys.php`.

---

## 5. Test it

With test keys in place, open `https://uptechify.in/payment.html`. The page
tells you it is in test mode.

Use Razorpay's test details:

| Method | What to use |
|---|---|
| UPI | `success@razorpay` to succeed, `failure@razorpay` to fail |
| Card | `4111 1111 1111 1111`, any future expiry, any CVV, OTP `1234` |
| Net Banking | pick any bank, then choose Success or Failure on their page |

Worth trying all four of these:

1. Pay successfully - you should land on the receipt page.
2. Close the Razorpay window halfway - you should get "Payment cancelled,
   nothing has been charged".
3. Use the failure UPI id - you should get the bank's reason back.
4. Pay on a phone - the same flow, laid out for a small screen.

Every one of them shows up in Dashboard -> **Transactions** while in Test Mode.

---

## 6. Go live

1. Switch the Razorpay dashboard to **Live Mode**.
2. Generate live keys and paste them into `keys.php` (they start with `rzp_live_`).
3. Add a **second webhook** for live mode, same URL, and put that secret in too
   (test and live webhooks are configured separately).
4. Make one real payment of Rs 1 to yourself and check it lands, then refund it
   from the dashboard.

The "test mode" notice on the payment page disappears on its own once live keys
are in - it reads the key prefix.

---

## 7. Setting your prices

Open `api/config.php` and look for `$SERVICES`.

```php
'web-design' => ['label' => 'Web Design', 'amount' => null],
```

- `'amount' => null` means **the customer types the amount** - use this for
  "pay what we quoted you" and invoice payments.
- `'amount' => 14999` means **fixed price**. The customer sees it, cannot edit
  it, and the server charges exactly that.

Right now every service is set to customer-entered, because you had not told me
your package prices yet. Change any line to a number and that option becomes a
fixed-price package immediately - no other file needs touching.

Important: the price the server uses always comes from this file. Even if
someone edits the page in their browser and tries to pay Rs 1 for a Rs 25,000
package, the server ignores it. That check is tested.

You can also send a customer a direct link with the amount filled in:

```
https://uptechify.in/payment.html?service=web-development&amount=15000&invoice=UPT-2026-014
```

---

## 8. Checking and managing payments

**Day to day - the Razorpay dashboard.** This is the source of truth for money.

- **Transactions -> Payments** - every payment, with status, method and fees
- **Transactions -> Settlements** - what actually reaches your bank, and when
  (Razorpay settles on a rolling cycle, usually T+2 working days)
- Click any payment to see the customer's name, email, phone, the service they
  chose and your invoice reference - those are attached to every order

**To refund someone:** open the payment in the dashboard, click **Refund**, and
choose full or partial. It reaches them in 5-7 working days. If you have the
`refund.processed` webhook on, your own log records it too.

**Your own records.** Every attempt is logged on your server, including the ones
that never became a payment - cancelled, failed, and any attempt to tamper with
a payment response. That is more than the dashboard shows you.

To download it as a spreadsheet, set `report_token` in `keys.php` to a long
random string, then open:

```
https://uptechify.in/api/export.php?token=YOUR_TOKEN
```

That gives you a CSV with date, status, receipt number, order and payment id,
amount, service, invoice reference and the customer's details. Leave
`report_token` blank and this download stays switched off.

**Statuses you will see:**

| Status | Meaning |
|---|---|
| `created` | The customer opened the payment window but has not finished |
| `paid` | Money collected and verified |
| `cancelled` | The customer closed the window. Nothing charged |
| `failed` | The bank declined it. Nothing charged |
| `invalid` | Someone sent a payment response that did not check out. Nothing charged |
| `refunded` | You refunded it from the dashboard |

---

## 9. How the security works, in plain terms

The reason there is a server side at all: Razorpay hands the result back to the
customer's browser, and a browser can be lied to. So the server never takes the
browser's word for anything.

1. The amount comes from `config.php`, never from the page.
2. When Razorpay reports a payment, the server checks the signature that came
   with it. That signature can only be produced by someone holding your key
   secret, which never leaves the server.
3. The server then asks Razorpay's API directly what that payment looks like,
   and refuses it if the amount or the order does not match what was ordered.
4. If your account authorises payments rather than capturing them, the server
   captures it, so money is not left sitting on hold.
5. The webhook does the same checks independently, so a customer closing their
   browser cannot lose you a payment.

A forged or altered payment response is recorded and rejected. No success page,
no order marked paid.

---

## 10. If something looks wrong

- **"Online payments are not switched on yet"** on the page - `keys.php` is
  missing or the keys are blank.
- **"Could not start the payment"** - the keys are wrong for the mode you are
  in, e.g. test keys while the dashboard is live. Check your host's PHP error
  log; the exact reason from Razorpay is written there.
- **Payments work but nothing is logged** - the folder above `public_html` is
  not writable. The code falls back to `api/../data` automatically and blocks
  it from the web, so nothing breaks and nothing is exposed.
- **A customer says they paid but you have no record** - search their email in
  Dashboard -> Transactions. If Razorpay has it, the webhook will have recorded
  it too; if the webhook was not set up yet, add it and the next ones are safe.
