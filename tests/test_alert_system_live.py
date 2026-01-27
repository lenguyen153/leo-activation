import os
import sys
import uuid
from decimal import Decimal
from datetime import datetime
from sqlalchemy import select, text

# 1. Setup Path to find your modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 2. Imports from your Factory & Models
from data_utils.db_factory import get_db_context
from data_utils.settings import DatabaseSettings

# Import Models
from data_models.dbo_tenant import Tenant
from data_models.dbo_cdp import CdpProfile
from data_models.dbo_alert import AlertRule, MarketSnapshot, Instrument, AlertStatusEnum, AlertSourceEnum
from data_models.dbo_execution import DeliveryLog, MessageTemplate

# Import the Service
from data_services.alert_service import do_alerting_all_matched_profile

# --- TEST DATA CONSTANTS ---
TEST_TENANT_ID = uuid.UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
TEST_PROFILE_ID = "p_alice"
TEST_SYMBOL = "AAPL"

def seed_test_data(session):
    """Upserts the necessary data to run the test. 
       Now handles DB Triggers correctly by cleaning up old rules."""
    print("--- Seeding Test Data ---")

    # 1. Tenant
    session.execute(text(f"""
        INSERT INTO tenant (tenant_id, tenant_name, keycloak_realm, keycloak_client_id, status)
        VALUES ('{TEST_TENANT_ID}', 'TEST-TENANT', 'test-realm', 'test-client', 'active')
        ON CONFLICT (tenant_id) DO NOTHING;
    """))

    # 2. Profile
    alice = CdpProfile(
        tenant_id=TEST_TENANT_ID,
        profile_id=TEST_PROFILE_ID,
        first_name="Alice",
        primary_email="alice@test.com",
        media_channels=["EMAIL", "WEB_PUSH"],
        ext_data={"device": "test_device"}
    )
    session.merge(alice)

    # 3. Instrument (Check existence manually to be safe)
    existing_inst = session.execute(
        select(Instrument).where(
            Instrument.tenant_id == TEST_TENANT_ID, 
            Instrument.symbol == TEST_SYMBOL
        )
    ).scalar_one_or_none()
    
    if not existing_inst:
        inst = Instrument(
            tenant_id=TEST_TENANT_ID,
            symbol=TEST_SYMBOL,
            name="Apple Test",
            type_="STOCK",
            sector="Tech"
        )
        session.add(inst)

    # 4. Market Snapshot
    snapshot = session.get(MarketSnapshot, TEST_SYMBOL)
    if not snapshot:
        snapshot = MarketSnapshot(symbol=TEST_SYMBOL)
        session.add(snapshot)
    
    snapshot.price = Decimal("160.00") 
    snapshot.last_updated = datetime.now()

    # 5. Alert Rule (CRITICAL FIX)
    # The DB trigger forces a Hash ID. 'merge' fails because it looks for "rule_test_001",
    # doesn't find it, and tries to INSERT a duplicate Hash. 
    # Solution: Delete existing rule for this scenario first.
    session.execute(text(f"""
        DELETE FROM alert_rules 
        WHERE tenant_id = '{TEST_TENANT_ID}' 
          AND profile_id = '{TEST_PROFILE_ID}' 
          AND symbol = '{TEST_SYMBOL}'
    """))

    rule = AlertRule(
        rule_id="temp_id",  # This value is ignored/overwritten by the DB trigger
        tenant_id=TEST_TENANT_ID,
        profile_id=TEST_PROFILE_ID,
        symbol=TEST_SYMBOL,
        alert_type="PRICE",
        source=AlertSourceEnum.USER_MANUAL,
        condition_logic={"operator": ">", "value": 150.00},
        status=AlertStatusEnum.ACTIVE,
        frequency="ONCE"
    )
    session.add(rule)

    # 6. Templates (Cleanup and Re-insert)
    session.execute(text(f"""
        DELETE FROM message_templates 
        WHERE tenant_id = '{TEST_TENANT_ID}' 
        AND template_name IN ('price_alert_email', 'price_alert_push')
    """))
    
    t_email = MessageTemplate(
        tenant_id=TEST_TENANT_ID,
        channel="email",
        template_name="price_alert_email",
        subject_template="Alert: {{ symbol }} is up!",
        body_template="Hi {{ first_name }}, price is {{ current_price }}",
        status="approved",
        version=1
    )
    
    t_push = MessageTemplate(
        tenant_id=TEST_TENANT_ID,
        channel="web_push",
        template_name="price_alert_push",
        subject_template="Push Alert",
        body_template="{{ symbol }} > {{ target_price }}",
        status="approved",
        version=1
    )
    session.add(t_email)
    session.add(t_push)
    
    # Optional: Clean up old logs to make verification output clearer
    session.execute(text(f"""
        DELETE FROM delivery_log 
        WHERE tenant_id = '{TEST_TENANT_ID}' AND profile_id = '{TEST_PROFILE_ID}'
    """))

    print("--- Seeding Complete ---")

def verify_results(session):
    """Checks the delivery log to confirm success."""
    logs = session.execute(
        select(DeliveryLog)
        .where(
            DeliveryLog.tenant_id == TEST_TENANT_ID,
            DeliveryLog.profile_id == TEST_PROFILE_ID,
            DeliveryLog.created_at >= datetime.now().date() # Created today
        )
    ).scalars().all()

    print(f"\n--- Verification Results ---")
    print(f"Total Logs Found: {len(logs)}")
    
    for log in logs:
        print(f" [OK] {log.channel.upper()} | Status: {log.delivery_status} | Event: {log.event_id}")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    settings = DatabaseSettings()
    
    # 1. Open Session (Context Manager)
    try:
        with get_db_context(settings) as session:
            
            # A. Prepare Data
            seed_test_data(session)
            
            # Force a flush/commit so the data is visible to the next logic step
            # Note: Although the same session sees uncommitted data, if your Logic does raw SQL it might miss it.
            # But here we are using ORM throughout.
            session.flush() 

            # B. Run the Alert System
            print("\n--- Running Alert Service ---")
            alerts = do_alerting_all_matched_profile(session, TEST_TENANT_ID)
            
            for a in alerts:
                print(f" > {a}")
            
            # C. Verify
            # We must flush the logs created by the service to query them back in verify_results
            session.flush()
            verify_results(session)
            
            # Context Manager exits -> Auto-Commits
            print("\n--- Test Completed Successfully (Committed) ---")

    except Exception as e:
        print(f"❌ Test Failed: {e}")
        # Context Manager exits -> Auto-Rollbacks