#!/usr/bin/env python3
"""
End-to-end tests for the Uptechify Razorpay integration.

Runs the real PHP endpoints against a stand-in Razorpay API, so every check
below exercises the code that will run in production - the signature check,
the amount check, the ledger, the webhook, the throttle.
"""
import hashlib
import hmac
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "deliverable"
TESTS = ROOT / "tests"
DATA = TESTS / "scratch-data"

SITE_PORT = 9100
MOCK_PORT = 9101
BASE = f"http://127.0.0.1:{SITE_PORT}"
MOCK = f"http://127.0.0.1:{MOCK_PORT}"

KEY_ID = "rzp_test_MOCK1234567890"
KEY_SECRET = "mockSecret_ThisIsOnlyForTesting"
WEBHOOK_SECRET = "mockWebhookSecret123"
REPORT_TOKEN = "mockReportToken_abcdef123456"

passed, failed = 0, 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}   {detail}")


def call(path, payload=None, method=None, headers=None, raw=None):
    url = path if path.startswith("http") else BASE + path
    data = None
    hdrs = {"Accept": "application/json"}
    if raw is not None:
        data = raw
        hdrs["Content-Type"] = "application/json"
    elif payload is not None:
        data = json.dumps(payload).encode()
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body or "{}")
        except json.JSONDecodeError:
            return e.code, {"raw": body}


def sign(order_id, payment_id):
    return hmac.new(KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def ledger():
    path = DATA / "transactions.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def events_for(order_id):
    return [row.get("event") for row in ledger() if row.get("order_id") == order_id]


def reset_throttle():
    """The per-IP throttle is real and would otherwise trip mid-suite. Each
    group starts from a clean slate; test_rate_limit deliberately does not."""
    f = DATA / "ratelimit.json"
    if f.exists():
        f.unlink()


def make_order(**overrides):
    payload = {
        "name": "Ravi Kumar",
        "email": "ravi@example.com",
        "phone": "9876543210",
        "service": "web-development",
        "amount": 15000,
        "invoice": "UPT-2026-014",
        "notes": "First milestone",
        "company_website": "",
    }
    payload.update(overrides)
    return call("/api/create-order.php", payload)


def mock_pay(order_id, **kwargs):
    body = {"order_id": order_id}
    body.update(kwargs)
    _, data = call(MOCK + "/_test/pay", body)
    return data["payment_id"]


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
def setup():
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)
    mock_store = pathlib.Path("/tmp/mock-rzp.json")
    if mock_store.exists():
        mock_store.unlink()

    (SITE / "api" / "keys.php").write_text(
        "<?php return [\n"
        f"    'key_id' => '{KEY_ID}',\n"
        f"    'key_secret' => '{KEY_SECRET}',\n"
        f"    'webhook_secret' => '{WEBHOOK_SECRET}',\n"
        f"    'report_token' => '{REPORT_TOKEN}',\n"
        "];\n"
    )

    env = dict(os.environ)
    # config.php lets environment variables override keys.php. If the machine
    # happens to carry real credentials, they must not leak into a test run -
    # a live key here would create real orders.
    for leftover in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        env.pop(leftover, None)
    env["RAZORPAY_API_BASE"] = MOCK
    env["UPTECHIFY_DATA_DIR"] = str(DATA)
    env["PHP_CLI_SERVER_WORKERS"] = "4"

    logs = TESTS / "logs"
    logs.mkdir(exist_ok=True)

    mock = subprocess.Popen(
        ["php", "-S", f"127.0.0.1:{MOCK_PORT}", str(TESTS / "mock-razorpay" / "router.php")],
        stdout=open(logs / "mock.log", "w"), stderr=subprocess.STDOUT,
    )
    site = subprocess.Popen(
        ["php", "-S", f"127.0.0.1:{SITE_PORT}", "-t", str(SITE)],
        env=env, stdout=open(logs / "site.log", "w"), stderr=subprocess.STDOUT,
    )

    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/api/services.php", timeout=2).read()
            urllib.request.urlopen(urllib.request.Request(MOCK + "/orders", data=b"{}", method="POST"), timeout=2)
            break
        except urllib.error.HTTPError:
            break
        except Exception:
            time.sleep(0.2)
    return mock, site


def teardown(procs):
    for p in procs:
        p.terminate()
    keys = SITE / "api" / "keys.php"
    if keys.exists():
        keys.unlink()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_services():
    print("\nService catalogue")
    reset_throttle()
    status, data = call("/api/services.php")
    check("services.php responds 200", status == 200, status)
    check("returns the service list", data.get("success") and len(data.get("services", [])) >= 5, data)
    check("reports keys are configured", data.get("ready") is True, data)
    check("reports test mode", data.get("mode") == "test", data)


def test_validation():
    print("\nInput validation (server side)")
    reset_throttle()
    cases = [
        ("empty name", {"name": ""}),
        ("one letter name", {"name": "R"}),
        ("malformed email", {"email": "ravi@@example"}),
        ("email with no domain", {"email": "ravi@"}),
        ("short phone", {"phone": "98765"}),
        ("letters in phone", {"phone": "abcdefghij"}),
        ("unknown service", {"service": "free-stuff"}),
        ("no service chosen", {"service": ""}),
        ("amount of zero", {"amount": 0}),
        ("negative amount", {"amount": -500}),
        ("amount over the cap", {"amount": 900000}),
        ("amount as text", {"amount": "fifteen thousand"}),
    ]
    for label, override in cases:
        status, data = make_order(**override)
        check(f"rejects {label}", status == 400 and not data.get("success"), f"{status} {data}")

    status, data = make_order(company_website="http://spam.example")
    check("rejects the honeypot being filled", status == 422, f"{status} {data}")

    # Control: the same payload with nothing wrong must succeed, otherwise the
    # rejections above prove nothing.
    status, data = make_order()
    check("CONTROL: a clean payload is accepted", status == 200 and data.get("success"), f"{status} {data}")
    return data


def test_happy_path():
    print("\nHappy path: create -> pay -> verify")
    reset_throttle()
    status, order = make_order(amount=15000)
    check("order created", status == 200 and order["order_id"].startswith("order_"), order)
    check("amount converted to paise", order["amount"] == 1500000, order)
    check("key id sent to the browser", order["key_id"] == KEY_ID, order)
    check("secret never sent to the browser", "secret" not in json.dumps(order).lower(), order)
    check("ledger has the created order", "order_created" in events_for(order["order_id"]), events_for(order["order_id"]))

    payment_id = mock_pay(order["order_id"])
    status, verified = call("/api/verify-payment.php", {
        "razorpay_order_id": order["order_id"],
        "razorpay_payment_id": payment_id,
        "razorpay_signature": sign(order["order_id"], payment_id),
    })
    check("verification succeeds", status == 200 and verified.get("success"), f"{status} {verified}")
    check("receipt token issued", len(verified.get("token", "")) == 32, verified)
    check("ledger marks it paid", any(
        r.get("order_id") == order["order_id"] and r.get("status") == "paid" for r in ledger()
    ), events_for(order["order_id"]))

    # The receipt endpoint
    status, receipt = call(f"/api/payment-status.php?order_id={order['order_id']}&token={verified['token']}")
    check("receipt readable with the right token", status == 200 and receipt["status"] == "paid", receipt)
    check("receipt shows the right amount", receipt["amount"] == 1500000, receipt)
    check("receipt shows the service", receipt["service"] == "Web Development", receipt)

    status, denied = call(f"/api/payment-status.php?order_id={order['order_id']}&token={'0' * 32}")
    check("receipt refused with a wrong token", status == 403, f"{status} {denied}")
    return order, payment_id, verified["token"]


def test_forged_signature():
    print("\nForged payment responses")
    reset_throttle()
    status, order = make_order(amount=25000)
    payment_id = mock_pay(order["order_id"])

    status, data = call("/api/verify-payment.php", {
        "razorpay_order_id": order["order_id"],
        "razorpay_payment_id": payment_id,
        "razorpay_signature": "f" * 64,
    })
    check("a made up signature is rejected", status == 400 and not data.get("success"), f"{status} {data}")
    check("the attempt is written to the ledger", "signature_mismatch" in events_for(order["order_id"]), events_for(order["order_id"]))
    check("the order is NOT marked paid", not any(
        r.get("order_id") == order["order_id"] and r.get("status") == "paid" for r in ledger()
    ))

    # Signature valid for a DIFFERENT pair - the classic replay attempt.
    _, other = make_order(amount=100)
    other_payment = mock_pay(other["order_id"])
    status, data = call("/api/verify-payment.php", {
        "razorpay_order_id": order["order_id"],
        "razorpay_payment_id": payment_id,
        "razorpay_signature": sign(other["order_id"], other_payment),
    })
    check("a signature from another payment is rejected", status == 400, f"{status} {data}")

    status, data = call("/api/verify-payment.php", {"razorpay_order_id": order["order_id"]})
    check("an incomplete response is rejected", status == 400, f"{status} {data}")


def test_amount_tampering():
    print("\nPaying less than the order")
    reset_throttle()
    status, order = make_order(amount=20000)
    # Razorpay says the payment is only Rs 1 even though the order was 20,000.
    payment_id = mock_pay(order["order_id"], amount=100)
    status, data = call("/api/verify-payment.php", {
        "razorpay_order_id": order["order_id"],
        "razorpay_payment_id": payment_id,
        "razorpay_signature": sign(order["order_id"], payment_id),
    })
    check("a short payment is rejected", status == 400, f"{status} {data}")
    check("mismatch recorded", "amount_mismatch" in events_for(order["order_id"]), events_for(order["order_id"]))

    # A payment that belongs to someone else's order.
    _, victim = make_order(amount=30000)
    stolen = mock_pay(victim["order_id"], claim_order_id="order_SOMETHINGELSE")
    status, data = call("/api/verify-payment.php", {
        "razorpay_order_id": victim["order_id"],
        "razorpay_payment_id": stolen,
        "razorpay_signature": sign(victim["order_id"], stolen),
    })
    check("a payment for another order is rejected", status == 400, f"{status} {data}")


def test_authorized_is_captured():
    print("\nAuthorised payments get captured")
    reset_throttle()
    _, order = make_order(amount=7500)
    payment_id = mock_pay(order["order_id"], status="authorized")
    status, data = call("/api/verify-payment.php", {
        "razorpay_order_id": order["order_id"],
        "razorpay_payment_id": payment_id,
        "razorpay_signature": sign(order["order_id"], payment_id),
    })
    check("authorised payment accepted", status == 200 and data.get("success"), f"{status} {data}")
    _, payment = call(f"{MOCK}/payments/{payment_id}")
    check("money actually captured, not left on hold", payment["status"] == "captured", payment)


def test_failed_and_cancelled():
    print("\nCancelled and failed attempts")
    reset_throttle()
    _, order = make_order(amount=5000)
    status, data = call("/api/cancel-order.php", {"order_id": order["order_id"], "outcome": "cancelled"})
    check("cancellation recorded", status == 200 and data["status"] == "cancelled", data)
    check("ledger shows cancelled", "payment_cancelled" in events_for(order["order_id"]), events_for(order["order_id"]))

    _, order2 = make_order(amount=5000)
    status, data = call("/api/cancel-order.php", {
        "order_id": order2["order_id"], "outcome": "failed", "reason": "Card declined by bank",
    })
    check("failure recorded separately from cancellation", data["status"] == "failed", data)
    check("reason kept", any(r.get("reason") == "Card declined by bank" for r in ledger()), ledger()[-1])

    status, data = call("/api/cancel-order.php", {"order_id": "order_DOESNOTEXIST"})
    check("unknown order refused", status == 404, f"{status} {data}")

    # A paid order must not be downgradable by a stray cancel call.
    _, order3 = make_order(amount=1200)
    payment_id = mock_pay(order3["order_id"])
    call("/api/verify-payment.php", {
        "razorpay_order_id": order3["order_id"],
        "razorpay_payment_id": payment_id,
        "razorpay_signature": sign(order3["order_id"], payment_id),
    })
    status, data = call("/api/cancel-order.php", {"order_id": order3["order_id"], "outcome": "cancelled"})
    check("a paid order cannot be flipped to cancelled", data.get("status") == "paid", data)


def test_webhook():
    print("\nWebhook")
    reset_throttle()
    _, order = make_order(amount=9000)
    body = json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": "pay_WEBHOOK1", "order_id": order["order_id"], "amount": 900000,
            "method": "card", "email": "ravi@example.com", "contact": "+919876543210", "fee": 212,
        }}},
    }).encode()
    good = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()

    status, _ = call("/api/webhook.php", raw=body, headers={"X-Razorpay-Signature": "deadbeef"})
    check("unsigned webhook rejected", status == 400, status)
    check("nothing written for the rejected call", "webhook_captured" not in events_for(order["order_id"]))

    status, _ = call("/api/webhook.php", raw=body, headers={"X-Razorpay-Signature": good})
    check("signed webhook accepted", status == 200, status)
    check("payment recorded from the webhook", "webhook_captured" in events_for(order["order_id"]), events_for(order["order_id"]))
    check("order now reads as paid", any(
        r.get("order_id") == order["order_id"] and r.get("status") == "paid" for r in ledger()
    ))

    # A webhook claiming a different amount than the order must not be trusted.
    _, order2 = make_order(amount=40000)
    body2 = json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": "pay_WEBHOOK2", "order_id": order2["order_id"], "amount": 100, "method": "upi",
        }}},
    }).encode()
    sig2 = hmac.new(WEBHOOK_SECRET.encode(), body2, hashlib.sha256).hexdigest()
    call("/api/webhook.php", raw=body2, headers={"X-Razorpay-Signature": sig2})
    check("a webhook with the wrong amount does not mark it paid", not any(
        r.get("order_id") == order2["order_id"] and r.get("status") == "paid" for r in ledger()
    ), events_for(order2["order_id"]))
    check("the mismatch is logged", "webhook_amount_mismatch" in events_for(order2["order_id"]), events_for(order2["order_id"]))

    # payment.failed
    _, order3 = make_order(amount=3000)
    body3 = json.dumps({
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_WEBHOOK3", "order_id": order3["order_id"], "amount": 300000,
            "error_description": "Payment was not completed on time",
        }}},
    }).encode()
    sig3 = hmac.new(WEBHOOK_SECRET.encode(), body3, hashlib.sha256).hexdigest()
    call("/api/webhook.php", raw=body3, headers={"X-Razorpay-Signature": sig3})
    check("failure webhook recorded", "webhook_failed" in events_for(order3["order_id"]), events_for(order3["order_id"]))


def test_csv_export():
    print("\nCSV export")
    reset_throttle()
    status, data = call("/api/export.php?token=wrong-token")
    check("a wrong token gets nothing", status == 403, f"{status} {data}")

    code, body = fetch_text(f"/api/export.php?token={REPORT_TOKEN}")
    check("the right token downloads the CSV", code == 200 and "Payment ID" in body, body[:120])
    check("paid orders are in it", "paid" in body, body[:200])
    check("amounts are in rupees, not paise", ",150.00," in body or ",15000.00," in body, body[:400])

    # One line per order, not one per event, even though the ledger records
    # several events for a single payment.
    lines = [l for l in body.splitlines() if l.strip()]
    ids = [l.split(",")[3] for l in lines[1:] if len(l.split(",")) > 3]
    check("each order appears once", len(ids) == len(set(ids)), f"{len(ids)} rows, {len(set(ids))} unique")


def test_method_guard():
    print("\nMethod guards")
    reset_throttle()
    status, _ = call("/api/create-order.php", method="GET")
    check("create-order refuses GET", status == 405, status)
    status, _ = call("/api/verify-payment.php", method="GET")
    check("verify-payment refuses GET", status == 405, status)


def test_rate_limit():
    print("\nThrottle")
    hit_limit = False
    for _ in range(30):
        status, _ = make_order(amount=100)
        if status == 429:
            hit_limit = True
            break
    check("repeated attempts get throttled", hit_limit, "no 429 after 30 attempts")


def test_data_not_public():
    print("\nPHP source is not readable over HTTP")
    reset_throttle()
    for path in ["/api/keys.php", "/api/config.php", "/api/lib.php"]:
        try:
            with urllib.request.urlopen(BASE + path, timeout=10) as r:
                text = r.read().decode(errors="replace")
            leaked = KEY_SECRET in text or "key_secret" in text
            check(f"{path} exposes nothing", not leaked, text[:200])
        except urllib.error.HTTPError as e:
            check(f"{path} is not served ({e.code})", True)


def fetch_text(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def test_webroot_fallback_is_unreadable():
    """
    The ledger normally lives above public_html. This checks the OTHER branch:
    when that folder cannot be written, the fallback inside the webroot must
    still be impossible to download.

    The built-in PHP server ignores .htaccess entirely - which is exactly the
    condition worth testing, because it isolates the second defence.
    """
    print("\nFallback ledger inside the webroot")
    reset_throttle()

    unwritable = TESTS / "scratch-data" / "not-writable"
    unwritable.mkdir(parents=True, exist_ok=True)
    unwritable.chmod(0o500)

    env = dict(os.environ)
    for leftover in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        env.pop(leftover, None)
    env["RAZORPAY_API_BASE"] = MOCK
    env["UPTECHIFY_DATA_DIR"] = str(unwritable / "cannot-create-here")
    env["PHP_CLI_SERVER_WORKERS"] = "4"

    port = 9102
    global BASE
    previous = BASE
    logs = TESTS / "logs"
    server = subprocess.Popen(
        ["php", "-S", f"127.0.0.1:{port}", "-t", str(SITE)],
        env=env, stdout=open(logs / "fallback.log", "w"), stderr=subprocess.STDOUT,
    )
    BASE = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/api/services.php", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)

        status, order = make_order(amount=4321, email="private.customer@example.com")
        check("orders still work when the preferred folder is unwritable",
              status == 200 and order.get("success"), f"{status} {order}")

        on_disk = SITE / "data" / "transactions.php"
        check("fallback ledger created inside the webroot", on_disk.exists(), str(on_disk))

        # POSITIVE CONTROL: the customer's email really is written in that file.
        # Without this, "not exposed" could just mean "nothing was recorded".
        raw = on_disk.read_text() if on_disk.exists() else ""
        check("CONTROL: the file on disk does contain the customer email",
              "private.customer@example.com" in raw, raw[:200])

        code, served = fetch_text("/data/transactions.php")
        check("the same file over HTTP leaks no customer data",
              "private.customer@example.com" not in served, f"{code} {served[:200]}")
        check("and it is not served as readable content", served.strip() == "", f"{code} {served[:200]}")

        code, served = fetch_text("/data/ratelimit.php")
        check("the IP list leaks nothing either", "127.0.0.1" not in served, f"{code} {served[:200]}")
    finally:
        server.terminate()
        BASE = previous
        unwritable.chmod(0o700)
        shutil.rmtree(SITE / "data", ignore_errors=True)


if __name__ == "__main__":
    procs = setup()
    try:
        test_services()
        test_validation()
        test_happy_path()
        test_forged_signature()
        test_amount_tampering()
        test_authorized_is_captured()
        test_failed_and_cancelled()
        test_webhook()
        test_csv_export()
        test_method_guard()
        test_data_not_public()
        test_webroot_fallback_is_unreadable()
        test_rate_limit()   # last: it exhausts the per-IP budget
    finally:
        teardown(procs)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
