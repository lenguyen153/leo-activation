import logging
from dotenv import load_dotenv

load_dotenv()

from agentic_tools.channels.email import EmailChannel
from agentic_tools.channels.helpers import MessageRenderer
from agentic_tools.channels.templates.email.stock_picks import (
    EMAIL_STOCK_PICKS_SUBJECT,
    EMAIL_STOCK_PICKS_HTML,
)
from agentic_tools.channels.templates.zalo.models import StockRecommendation

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# --- Dummy stock data for testing ---
SAMPLE_STOCKS = [
    StockRecommendation(
        symbol="VNM",
        industry="Thực phẩm & Đồ uống",
        exchange="HOSE",
        rank=1,
        score=0.87,
        reasons=[
            "Doanh thu Q1 tăng 12% so với cùng kỳ",
            "Tỷ suất lợi nhuận ổn định trên 20%",
            "Được khuyến nghị MUA bởi 8/10 phân tích viên",
        ],
    ),
    StockRecommendation(
        symbol="FPT",
        industry="Công nghệ thông tin",
        exchange="HOSE",
        rank=2,
        score=0.75,
        reasons=[
            "Mảng xuất khẩu phần mềm tăng trưởng mạnh",
            "Ký kết hợp đồng mới với đối tác Nhật Bản",
        ],
    ),
]


def run_test(recipients: list):
    channel = EmailChannel()
    renderer = MessageRenderer()

    print(f"Provider: {channel.provider}")

    html_body = renderer.render_email_template(
        EMAIL_STOCK_PICKS_HTML,
        profile={"email": recipients[0]},
        stocks=SAMPLE_STOCKS,
    )

    print(f"Sending to: {recipients}")
    if channel.provider == "brevo":
        res = channel.send_via_brevo_api(recipients, EMAIL_STOCK_PICKS_SUBJECT, html_body)
    elif channel.provider == "sendgrid":
        res = channel.send_via_sendgrid_api(recipients, EMAIL_STOCK_PICKS_SUBJECT, html_body)
    else:
        res = channel.send_via_smtp(recipients, EMAIL_STOCK_PICKS_SUBJECT, html_body)

    if res.get("status") == "success":
        print(f"✅ Sent! {res}")
    else:
        print(f"❌ Failed: {res}")


if __name__ == "__main__":
    TARGET_EMAILS = ["your-email@example.com"]
    run_test(TARGET_EMAILS)
