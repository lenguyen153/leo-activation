import uuid
import logging
import random
from decimal import Decimal
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import select
from jinja2 import Template

# Imports based on your project structure
from data_models.dbo_alert import AlertRule, MarketSnapshot, AlertStatusEnum
from data_models.dbo_execution import DeliveryLog, MessageTemplate
from data_models.dbo_cdp import CdpProfile 

logger = logging.getLogger(__name__)

def _get_mock_graph_recommendation_score(profile_id: str, symbol: str) -> Decimal:
    """
    MOCK: Simulates querying the Interest Graph (Apache AGE) to get a recommendation score.
    In production, this would execute a Cypher query like:
    MATCH (p:Profile {id: %s})-[r:RECOMMEND]->(n:News)-[:ABOUT]->(s:Stock {symbol: %s}) RETURN r.score
    """
    # Return a random score between 0.0 and 1.0 for simulation
    return Decimal(str(round(random.uniform(0.1, 0.99), 2)))

def evaluate_condition(metric_value: Decimal | None, condition: dict) -> bool:
    """
    Evaluates rule logic.
    :param metric_value: The value to test (Price for standard/follow, Score for recommend).
    :param condition: The JSON logic (e.g. {'operator': '>', 'value': 150}).
    """
    if metric_value is None or not condition:
        return False
        
    operator = condition.get("operator")
    
    # --- 1. NEW: FOLLOW OPERATOR ---
    # Logic: If user follows the stock, ANY valid update triggers the alert.
    if operator == "FOLLOW":
        return True # logic: if we are here, 'metric_value' (price) exists, so it's an update.

    # --- 2. NEW: RECOMMEND OPERATOR ---
    # Logic: If recommendation_score > MINIMUM_TO_ALERT (threshold)
    if operator == "RECOMMEND":
        # For RECOMMEND, 'metric_value' passed in is the Score, not the Price.
        try:
            threshold = Decimal(str(condition.get("threshold", 0.5))) # Default threshold 0.5
            return metric_value > threshold
        except:
            return False

    # --- STANDARD PRICE OPERATORS ---
    # Robust conversion of the target value
    try:
        target_value = Decimal(str(condition.get("value", 0)))
    except:
        return False
    
    if operator == ">":
        return metric_value > target_value
    elif operator == ">=":
        return metric_value >= target_value
    elif operator == "<":
        return metric_value < target_value
    elif operator == "<=":
        return metric_value <= target_value
    elif operator == "==":
        return metric_value == target_value
    
    return False

def render_message(template_str: str, context: dict) -> str:
    """Renders a Jinja2 string with the provided context."""
    if not template_str:
        return ""
    try:
        return Template(template_str).render(**context)
    except Exception as e:
        logger.error(f"Template rendering failed: {e}")
        return template_str

def do_alerting_all_matched_profile(session: Session, tenant_id: uuid.UUID):
    """
    Core Logic:
    1. Scan active AlertRules for the given tenant.
    2. Join with MarketSnapshot (live prices) and CdpProfile (user contact info).
    3. Determine metric (Price vs Score).
    4. If condition met, fetch MessageTemplate and generate DeliveryLog.
    """
    logger.info(f"Starting alert check for tenant {tenant_id}")

    # 1. Query: Join Rules -> Market Data -> Profile
    stmt = (
        select(AlertRule, MarketSnapshot, CdpProfile)
        .join(MarketSnapshot, AlertRule.symbol == MarketSnapshot.symbol)
        .join(CdpProfile, AlertRule.profile_id == CdpProfile.profile_id)
        .where(
            AlertRule.tenant_id == tenant_id,
            AlertRule.status == AlertStatusEnum.ACTIVE
        )
    )
    
    results = session.execute(stmt).all()

    # 2. Pre-fetch Templates
    # We fetch templates for Price, Follow, and Recommendation
    # Assuming 'recommend_alert_email' exists for the RECOMMEND case
    target_templates = ['price_alert_email', 'price_alert_push', 'recommend_alert_email', 'follow_alert_email']
    
    templates_stmt = (
        select(MessageTemplate)
        .where(
            MessageTemplate.tenant_id == tenant_id,
            MessageTemplate.status == 'approved',
            MessageTemplate.template_name.in_(target_templates)
        )
    )
    templates = session.execute(templates_stmt).scalars().all()
    
    # Map templates: key = template_name (or we can map by channel if names are standard)
    # For simplicity, let's map by name
    tmpl_map = {t.template_name: t for t in templates}
    
    generated_alerts = []

    # 3. Process Rules
    for rule, market, profile in results:
        
        condition = rule.condition_logic
        operator = condition.get("operator")
        
        # --- A. Determine Metric Value ---
        if operator == "RECOMMEND":
            # For recommendations, we need the Graph Score
            current_metric = _get_mock_graph_recommendation_score(profile.profile_id, rule.symbol)
            logger.debug(f"Calculated Score for {profile.profile_id}/{rule.symbol}: {current_metric}")
        else:
            # For FOLLOW or Standard Price alerts, we use the Market Price
            current_metric = market.price

        # --- B. Evaluate ---
        is_triggered = evaluate_condition(current_metric, condition)
        
        if is_triggered:
            logger.info(f"Rule {rule.rule_id} ({operator}) triggered for {profile.primary_email}")
            
            # Prepare Context
            context = {
                "first_name": profile.first_name,
                "symbol": rule.symbol,
                "current_price": f"{market.price:,.2f}",
                "metric_value": str(current_metric), # Price or Score
                "alert_id": rule.rule_id
            }

            # --- C. Select Templates based on Operator ---
            # Default to price alert
            email_tmpl_name = "price_alert_email"
            push_tmpl_name = "price_alert_push"

            if operator == "RECOMMEND":
                email_tmpl_name = "recommend_alert_email"
                push_tmpl_name = None # Disable push for recommend if not needed
            elif operator == "FOLLOW":
                email_tmpl_name = "follow_alert_email"
                push_tmpl_name = "price_alert_push" # Re-use price push for updates

            # --- D. PROCESS EMAIL ---
            if profile.media_channels and "EMAIL" in profile.media_channels:
                tmpl = tmpl_map.get(email_tmpl_name)
                if tmpl:
                    subject = render_message(tmpl.subject_template, context)
                    # body = render_message(tmpl.body_template, context) 
                    
                    log = DeliveryLog(
                        tenant_id=tenant_id,
                        event_id=f"ALERT_{rule.rule_id}_{datetime.now().timestamp()}",
                        profile_id=profile.profile_id,
                        channel="email",
                        delivery_status="SENT", 
                        provider_response={"mock_id": f"ses_{uuid.uuid4()}"},
                        sent_at=datetime.now()
                    )
                    session.add(log)
                    generated_alerts.append(f"EMAIL ({operator}) to {profile.primary_email}: {subject}")

            # --- E. PROCESS WEB PUSH ---
            if profile.media_channels and "WEB_PUSH" in profile.media_channels and push_tmpl_name:
                tmpl = tmpl_map.get(push_tmpl_name)
                if tmpl:
                    body = render_message(tmpl.body_template, context)
                    
                    log = DeliveryLog(
                        tenant_id=tenant_id,
                        event_id=f"ALERT_{rule.rule_id}_{datetime.now().timestamp()}",
                        profile_id=profile.profile_id,
                        channel="web_push",
                        delivery_status="SENT",
                        provider_response={"mock_id": f"fcm_{uuid.uuid4()}"},
                        sent_at=datetime.now()
                    )
                    session.add(log)
                    generated_alerts.append(f"PUSH ({operator}) to {profile.profile_id}: {body}")
    
    return generated_alerts