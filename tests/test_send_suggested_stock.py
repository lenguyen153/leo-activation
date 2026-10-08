import logging
from dotenv import load_dotenv

load_dotenv()

from agentic_tools.channels.zalo import ZaloOAChannel
from agentic_tools.channels.templates.zalo.suggested_stock import SUGGESTED_STOCK_TEMPLATE
from data_utils.settings import DatabaseSettings

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def run_campaign(uids: list):
    db = DatabaseSettings().get_arango_db()
    channel = ZaloOAChannel(db_client=db)

    for uid in uids:
        print(f"📡 Sending suggested stocks to: {uid}")
        success, code, msg = channel.send_suggested_stock(
            zalo_user_id=uid,
            template=SUGGESTED_STOCK_TEMPLATE,
        )
        if success:
            print(f"✅ Success! (ID: {msg})")
        else:
            print(f"❌ Failed: {code} - {msg}")

if __name__ == "__main__":
    TARGET_USERS = ["6641036126670172018"]
    run_campaign(TARGET_USERS)
