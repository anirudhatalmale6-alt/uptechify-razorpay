#!/usr/bin/env python3
"""
Drives payment.html in a real browser: fills the form, opens a stand-in for the
Razorpay window, completes the payment, and follows the redirect to the receipt.
Also captures screenshots at desktop and phone widths.
"""
import json
import os
import pathlib
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "deliverable"
TESTS = ROOT / "tests"
SHOTS = TESTS / "screenshots"
DATA = TESTS / "scratch-browser-data"

SITE_PORT = 9110
MOCK_PORT = 9111
BASE = f"http://127.0.0.1:{SITE_PORT}"
MOCK = f"http://127.0.0.1:{MOCK_PORT}"

KEY_ID = "rzp_test_MOCK1234567890"
KEY_SECRET = "mockSecret_ThisIsOnlyForTesting"

passed, failed = 0, 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}   {detail}")


CHECKOUT_JS = "**checkout.razorpay.com**"


def stub_checkout(page):
    """
    The real checkout.js loads fine, but it cannot open a payment window with a
    made-up key - it just 401s. So for the flow tests the real script is blocked
    and this stand-in takes its place. It plays Razorpay's part only: it asks
    the test signer for a correctly signed response and hands it to the page's
    own handler. Nothing in the page under test is changed.

    test_real_checkout_script_loads() covers the other half - that the genuine
    script is reachable and does define window.Razorpay.
    """
    page.route(CHECKOUT_JS, lambda route: route.abort())
    page.add_init_script(STUB)


STUB = """
window.__rzpEvents = [];
window.Razorpay = function (options) {
    window.__rzpOptions = options;
    return {
        on: function (event, callback) { (window.__rzpHandlers = window.__rzpHandlers || {})[event] = callback; },
        open: function () {
            window.__rzpEvents.push('opened');
            var modal = document.createElement('div');
            modal.id = 'stub-razorpay-modal';
            modal.style.cssText = 'position:fixed;inset:0;background:rgba(11,26,51,.75);z-index:9999;display:flex;align-items:center;justify-content:center;';
            modal.innerHTML = '<div style="background:#fff;padding:32px;border-radius:12px;font-family:Poppins,sans-serif;text-align:center;max-width:340px">'
                + '<div style="font-size:13px;color:#64748B;margin-bottom:6px">Razorpay (test stand-in)</div>'
                + '<div style="font-size:26px;font-weight:700;color:#0B1A33">Rs ' + (options.amount / 100).toLocaleString('en-IN') + '</div>'
                + '<div style="font-size:14px;color:#64748B;margin:6px 0 20px">' + options.description + '</div>'
                + '<button id="stub-pay" style="width:100%;padding:12px;border:0;border-radius:8px;background:#0066FF;color:#fff;font-size:15px;cursor:pointer">Pay with UPI</button>'
                + '<button id="stub-close" style="width:100%;padding:12px;margin-top:10px;border:1px solid #E2E8F0;border-radius:8px;background:#fff;color:#64748B;font-size:15px;cursor:pointer">Close</button>'
                + '</div>';
            document.body.appendChild(modal);

            document.getElementById('stub-pay').onclick = function () {
                fetch('api/test-sign.php', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({order_id: options.order_id})
                }).then(function (r) { return r.json(); }).then(function (signed) {
                    modal.remove();
                    options.handler(signed);
                });
            };
            document.getElementById('stub-close').onclick = function () {
                modal.remove();
                if (options.modal && options.modal.ondismiss) { options.modal.ondismiss(); }
            };
        }
    };
};
"""


def start_servers():
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    store = pathlib.Path("/tmp/mock-rzp.json")
    if store.exists():
        store.unlink()

    (SITE / "api" / "keys.php").write_text(
        "<?php return [\n"
        f"    'key_id' => '{KEY_ID}',\n"
        f"    'key_secret' => '{KEY_SECRET}',\n"
        "    'webhook_secret' => 'mockWebhookSecret123',\n"
        "];\n"
    )
    shutil.copy(TESTS / "test-sign.php", SITE / "api" / "test-sign.php")

    env = dict(os.environ)
    for leftover in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        env.pop(leftover, None)
    env["RAZORPAY_API_BASE"] = MOCK
    env["UPTECHIFY_DATA_DIR"] = str(DATA)
    env["PHP_CLI_SERVER_WORKERS"] = "6"

    logs = TESTS / "logs"
    logs.mkdir(exist_ok=True)
    mock = subprocess.Popen(
        ["php", "-S", f"127.0.0.1:{MOCK_PORT}", str(TESTS / "mock-razorpay" / "router.php")],
        stdout=open(logs / "browser-mock.log", "w"), stderr=subprocess.STDOUT,
    )
    site = subprocess.Popen(
        ["php", "-S", f"127.0.0.1:{SITE_PORT}", "-t", str(SITE)],
        env=env, stdout=open(logs / "browser-site.log", "w"), stderr=subprocess.STDOUT,
    )
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/api/services.php", timeout=2).read()
            break
        except Exception:
            time.sleep(0.2)
    return mock, site


def stop_servers(procs):
    for p in procs:
        p.terminate()
    for leftover in ["keys.php", "test-sign.php"]:
        f = SITE / "api" / leftover
        if f.exists():
            f.unlink()


def fill_form(page, amount="18500"):
    page.fill("#payName", "Ravi Kumar")
    page.fill("#payPhone", "9876543210")
    page.fill("#payEmail", "ravi.kumar@example.com")
    page.select_option("#payService", "web-development")
    page.fill("#payAmount", amount)
    page.fill("#payInvoice", "UPT-2026-014")


def run():
    procs = start_servers()
    errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()

            # ---------------- desktop ----------------
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            stub_checkout(page)

            print("\nPayment page")
            page.goto(BASE + "/payment.html", wait_until="networkidle")
            check("page loads", "Make a Payment" in page.inner_text("h1"), page.title())
            options = page.eval_on_selector_all("#payService option", "els => els.map(e => e.value)")
            check("services loaded into the dropdown", len(options) >= 6, options)
            check("Pay Now is in the navigation",
                  page.locator('.nav-list a[href="payment.html"]').count() == 1)

            # These start hidden. Asserting that here is what stops the later
            # "it appeared" checks from passing on something that was simply
            # always on screen.
            check("the total bar starts hidden", not page.locator("#paySummary").is_visible())
            # In test mode the page deliberately shows one info notice on load,
            # so "hidden" is not the right control here - "not an error" is.
            alert_class = page.get_attribute("#payAlert", "class") or ""
            check("no error is shown before the customer does anything",
                  not page.locator("#payAlert").is_visible() or "info" in alert_class,
                  f"visible={page.locator('#payAlert').is_visible()} class={alert_class!r}")
            check("the page opens at the top, not scrolled down",
                  page.evaluate("window.scrollY") < 10, page.evaluate("window.scrollY"))
            check("the header sits on one row",
                  page.eval_on_selector(".navbar", "el => el.getBoundingClientRect().height") < 110,
                  page.eval_on_selector(".navbar", "el => el.getBoundingClientRect().height"))
            page.screenshot(path=str(SHOTS / "01-payment-desktop.png"))

            print("\nForm validation in the browser")
            page.click("#payButton")
            page.wait_for_selector("#payAlert:not([hidden])")
            check("empty form is refused", "name" in page.inner_text("#payAlert").lower(),
                  page.inner_text("#payAlert"))
            check("and it is styled as an error, not a notice",
                  "info" not in (page.get_attribute("#payAlert", "class") or ""),
                  page.get_attribute("#payAlert", "class"))

            page.fill("#payName", "Ravi Kumar")
            page.fill("#payPhone", "12345")
            page.fill("#payEmail", "not-an-email")
            page.click("#payButton")
            check("bad email is caught", "email" in page.inner_text("#payAlert").lower(),
                  page.inner_text("#payAlert"))
            page.fill("#payEmail", "ravi.kumar@example.com")
            page.click("#payButton")
            check("short phone is caught", "phone" in page.inner_text("#payAlert").lower(),
                  page.inner_text("#payAlert"))

            print("\nLive total")
            fill_form(page)
            page.wait_for_selector("#paySummary:not([hidden])")
            check("total shown to the customer", "18,500" in page.inner_text("#paySummaryAmount"),
                  page.inner_text("#paySummaryAmount"))
            page.screenshot(path=str(SHOTS / "02-payment-filled.png"))

            print("\nCancelling")
            page.click("#payButton")
            page.wait_for_selector("#stub-razorpay-modal")
            page.screenshot(path=str(SHOTS / "03-checkout-open.png"))
            page.click("#stub-close")
            page.wait_for_selector("#payAlert:not([hidden])")
            check("cancelling says nothing was charged",
                  "cancelled" in page.inner_text("#payAlert").lower()
                  and "nothing has been charged" in page.inner_text("#payAlert").lower(),
                  page.inner_text("#payAlert"))
            check("the button is usable again", page.is_enabled("#payButton"))
            page.screenshot(path=str(SHOTS / "04-cancelled.png"))

            print("\nPaying")
            page.click("#payButton")
            page.wait_for_selector("#stub-razorpay-modal")
            page.click("#stub-pay")
            page.wait_for_url("**/payment-success.html*", timeout=15000)
            page.wait_for_selector("#receipt:not([hidden])", timeout=10000)
            receipt = page.inner_text("#receipt")
            check("receipt shows the amount", "18,500" in receipt, receipt)
            check("receipt shows the payment id", "pay_MOCK" in receipt, receipt)
            check("receipt shows the service", "Web Development" in receipt, receipt)
            check("thank-you wording is right", "went through" in page.inner_text("#resultTitle"),
                  page.inner_text("#resultTitle"))
            page.screenshot(path=str(SHOTS / "05-success-desktop.png"))

            print("\nReceipt page opened directly")
            page.goto(BASE + "/payment-success.html", wait_until="networkidle")
            check("does not pretend a payment happened",
                  "No payment to show" in page.inner_text("#resultTitle"), page.inner_text("#resultTitle"))

            print("\nFailure page")
            page.goto(BASE + "/payment-failed.html?status=cancelled&order_id=order_MOCK123&reason=Card+declined+by+bank",
                      wait_until="networkidle")
            check("failure page explains nothing was charged",
                  "nothing has been charged" in page.inner_text("#resultMessage").lower(),
                  page.inner_text("#resultMessage"))
            check("reason from the url is shown as text",
                  "Card declined by bank" in page.inner_text("#rcReason"), page.inner_text("#rcReason"))
            page.screenshot(path=str(SHOTS / "06-failed-desktop.png"))

            # Injected markup in the url must never become HTML.
            page.goto(BASE + "/payment-failed.html?reason=<img src=x onerror=alert(1)>", wait_until="networkidle")
            check("html in the url is not rendered",
                  page.locator("#rcReason img").count() == 0, page.inner_html("#rcReason"))

            page.close()

            # ---------------- phone ----------------
            print("\nPhone layout (iPhone-sized viewport)")
            mobile = browser.new_page(viewport={"width": 390, "height": 780}, is_mobile=True,
                                      has_touch=True, device_scale_factor=2)
            mobile.on("pageerror", lambda e: errors.append(str(e)))
            stub_checkout(mobile)
            mobile.goto(BASE + "/payment.html", wait_until="networkidle")
            mobile.screenshot(path=str(SHOTS / "07-payment-mobile.png"))

            overflow = mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
            check("no sideways scrolling on a phone", not overflow,
                  mobile.evaluate("document.documentElement.scrollWidth"))

            # The menu button has to actually open the menu.
            mobile.click("#navToggle")
            mobile.wait_for_timeout(400)
            check("mobile menu opens", mobile.locator("#navList.active").count() == 1)
            check("Pay Now is reachable from the mobile menu",
                  mobile.locator('#navList a[href="payment.html"]').is_visible())
            mobile.screenshot(path=str(SHOTS / "08-mobile-menu.png"))
            mobile.click("#navToggle")
            mobile.wait_for_timeout(400)

            # Inputs must be at least 16px or iOS zooms the page on focus.
            font = mobile.eval_on_selector("#payName", "el => getComputedStyle(el).fontSize")
            check("inputs are 16px so phones do not zoom in", float(font.replace("px", "")) >= 16, font)

            fill_form(mobile, amount="7500")
            mobile.wait_for_selector("#paySummary:not([hidden])")
            mobile.screenshot(path=str(SHOTS / "09-mobile-filled.png"))
            mobile.click("#payButton")
            mobile.wait_for_selector("#stub-razorpay-modal")
            mobile.click("#stub-pay")
            mobile.wait_for_url("**/payment-success.html*", timeout=15000)
            mobile.wait_for_selector("#receipt:not([hidden])", timeout=10000)
            check("payment completes on a phone too", "7,500" in mobile.inner_text("#receipt"),
                  mobile.inner_text("#receipt"))
            mobile.screenshot(path=str(SHOTS / "10-success-mobile.png"))
            mobile.close()

            # ---- the genuine checkout script -------------------------------
            # Everything above ran against a stand-in. This one loads the real
            # thing, so a broken script tag or a wrong URL cannot hide behind
            # the stub.
            print("\nThe real Razorpay checkout script")
            live = browser.new_page(viewport={"width": 1280, "height": 800})
            requested = []
            live.on("request", lambda r: requested.append(r.url) if "checkout.razorpay.com" in r.url else None)
            live.goto(BASE + "/payment.html", wait_until="networkidle")
            check("the page asks for checkout.razorpay.com", any(requested), requested)
            check("the real script defines Razorpay",
                  live.evaluate("typeof window.Razorpay === 'function'"))
            check("our page is not accidentally using the stub",
                  "stub-razorpay-modal" not in live.evaluate("String(window.Razorpay)"))
            live.close()

            browser.close()


        # ERR_FAILED is the harness itself blocking checkout.razorpay.com.
        ignore = ("favicon", "404", "ERR_FAILED")
        real = [e for e in errors if not any(i.lower() in e.lower() for i in ignore)]
        check("no javascript errors anywhere", not real, real[:3])
    finally:
        stop_servers(procs)

    print(f"\n{passed} passed, {failed} failed")
    print(f"Screenshots in {SHOTS}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
