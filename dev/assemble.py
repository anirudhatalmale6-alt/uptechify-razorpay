#!/usr/bin/env python3
"""
Builds payment.html, payment-success.html and payment-failed.html by reusing
the real head, header and footer from the live site, so the new pages inherit
the existing styling instead of guessing at it.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent
PARTS = ROOT / "parts"
OUT = ROOT / "deliverable"


SOURCE = ROOT.parent / "site" / "contact.html"


def part(name):
    return (PARTS / name).read_text(encoding="utf-8")


def slice_source(open_tag, close_tag, text):
    """
    Pulls a block out of the live page by its tags rather than by line number,
    so a shifted line can never truncate a script half way through.
    """
    start = text.index(open_tag)
    end = text.index(close_tag, start) + len(close_tag)
    return text[start:end]


SRC = SOURCE.read_text(encoding="utf-8")

HEAD = SRC[: SRC.index("</head>") + len("</head>")]
HEADER = slice_source("<header", "</header>", SRC)
FOOTER = slice_source("<footer", "</footer>", SRC)
# Everything after the footer up to </body> is the site's shared JS.
SHARED_JS = SRC[SRC.index("</footer>") + len("</footer>") : SRC.index("</body>")]
EXTRA_CSS = part("payment-style.html")

for label, block in [("header", HEADER), ("footer", FOOTER), ("shared js", SHARED_JS)]:
    opens, closes = block.count("<script"), block.count("</script>")
    assert opens == closes, f"{label}: {opens} <script> vs {closes} </script> - block is truncated"


def head_for(title, description, active):
    head = HEAD
    head = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", head, flags=re.S)
    head = re.sub(
        r'<meta name="description" content=".*?">',
        f'<meta name="description" content="{description}">',
        head,
        flags=re.S,
    )
    # Drop the contact page's own form handler styling hooks? Not needed -
    # only the payment CSS is appended, right before </head>.
    return head.replace("</head>", EXTRA_CSS + "</head>")


NAV_ITEM = (
    '          <li class="nav-item">'
    '<a href="payment.html" class="nav-link">Pay Now</a></li>\n'
)
CONTACT_ITEM = (
    '<li class="nav-item"><a href="contact.html" class="nav-link">Contact</a></li>'
)


def header_for(active):
    """Add the Pay Now entries and mark the right nav item active."""
    header = HEADER.replace('class="nav-link active"', 'class="nav-link"')

    # Menu entry, sitting just before Contact. This is the one that shows in
    # the mobile menu.
    line = [l for l in header.splitlines() if CONTACT_ITEM in l]
    if line:
        indent = line[0][: len(line[0]) - len(line[0].lstrip())]
        header = header.replace(
            line[0],
            f'{indent}<li class="nav-item"><a href="payment.html" class="nav-link">Pay Now</a></li>\n{line[0]}',
        )

    if active:
        header = header.replace(
            f'href="{active}" class="nav-link"',
            f'href="{active}" class="nav-link active"',
        )
    return header


def build(filename, title, description, body_part, script_part, active=None):
    page = (
        head_for(title, description, active)
        + "<body>\n\n"
        + header_for(active)
        + "\n"
        + part(body_part)
        + "\n"
        + FOOTER
        + "\n"
        + SHARED_JS
        + "\n"
        + part(script_part)
        + "\n</body>\n</html>\n"
    )
    opens, closes = page.count("<script"), page.count("</script>")
    assert opens == closes, f"{filename}: unbalanced script tags ({opens}/{closes})"
    assert page.count("<body>") == 1 and page.count("</body>") == 1, f"{filename}: body tags"

    (OUT / filename).write_text(page, encoding="utf-8")
    print(f"  {filename}  ({len(page):,} bytes, {opens} script blocks)")


print("Building payment pages...")
build(
    "payment.html",
    "Make a Payment | Uptechify",
    "Pay Uptechify securely online by UPI, card, net banking or wallet. Payments processed by Razorpay.",
    "payment-body.html",
    "payment-script.html",
    active="payment.html",
)
build(
    "payment-success.html",
    "Payment Successful | Uptechify",
    "Your payment to Uptechify has been received.",
    "success-body.html",
    "success-script.html",
)
build(
    "payment-failed.html",
    "Payment Not Completed | Uptechify",
    "Your payment to Uptechify was not completed. Nothing has been charged.",
    "failed-body.html",
    "failed-script.html",
)
print("Done.")
