"""
Fetch real stock recommendations from the API, render the email template,
and save to HTML for preview. Does NOT send anything.

Usage:
    python tests/preview_email.py
    explorer.exe email_preview.html   # open in Windows browser (WSL2)
"""
import requests
from dotenv import load_dotenv

load_dotenv()

from agentic_tools.channels.helpers import MessageRenderer
from agentic_tools.channels.templates.email.stock_picks import (
    EMAIL_STOCK_PICKS_SUBJECT,
    EMAIL_STOCK_PICKS_HTML,
)
from agentic_tools.channels.templates.zalo.models import StockRecommendation

OUTPUT_PATH = "email_preview.html"

if __name__ == "__main__":
    # Fetch real stocks — same call as dispatch_suggested_stock_batch
    resp = requests.get(
        "https://news-analysis.innotech.vn/api/v1/stock/recommend_stock",
        params={"top_n": 20},
        timeout=10,
    )
    resp.raise_for_status()
    stocks = [StockRecommendation(**s) for s in resp.json().get("recommendations", [])]

    if not stocks:
        print("No stocks returned from API.")
        raise SystemExit(1)

    print(f"Fetched {len(stocks)} stocks from API.")

    html = MessageRenderer().render_email_template(
        EMAIL_STOCK_PICKS_HTML,
        profile={"email": "nguyen.trinh@innotech.vn"},
        stocks=stocks,
    )

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Subject : {EMAIL_STOCK_PICKS_SUBJECT}")
    print(f"Saved to: {OUTPUT_PATH}")
    print()
    print("Open in browser (WSL2):")
    print(f"  explorer.exe {OUTPUT_PATH}")

    # Send via SMTP
    from agentic_tools.channels.email import EmailChannel
    channel = EmailChannel()
    res = channel.send_via_smtp(["nguyen.trinh@innotech.vn"], EMAIL_STOCK_PICKS_SUBJECT, html)
    if res.get("status") == "success":
        print("✅ Email sent to nguyen.trinh@innotech.vn")
    else:
        print(f"❌ Send failed: {res}")
