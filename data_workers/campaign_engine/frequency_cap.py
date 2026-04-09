"""
Two-layer frequency capping: Redis (fast path) + delivery_log (ground truth).

Redis key patterns
------------------
- Campaign cooldown:  leo:campaign:{rule_id}:{profile_id}:last_sent   TTL = cooldown_days * 86400
- Global daily count: leo:notif:daily:{profile_id}:{YYYY-MM-DD}       TTL = 86400
- Last-notification:  leo:notif:last:{profile_id}                      TTL = min_cooldown_hours * 3600
"""

import logging
from datetime import date, datetime, timezone

from main_configs import CampaignEngineConfigs

logger = logging.getLogger(__name__)


def check_frequency_cap(
    redis_client,
    rule_id: str,
    profile_id: str,
    frequency_cap: dict,
) -> bool:
    """
    Return True if the profile is eligible to receive this campaign.
    Checks in order (cheapest first):
      1. Global daily cap
      2. Min cooldown between any notifications
      3. Campaign-specific cooldown
    """
    today_str = date.today().isoformat()
    max_per_day = frequency_cap.get("max_per_day", CampaignEngineConfigs.MAX_NOTIFICATIONS_PER_DAY)
    cooldown_days = frequency_cap.get("cooldown_days", 7)
    min_cooldown_h = CampaignEngineConfigs.MIN_COOLDOWN_HOURS

    # 1. Global daily cap
    daily_key = f"leo:notif:daily:{profile_id}:{today_str}"
    daily_count = redis_client.get(daily_key)
    if daily_count and int(daily_count) >= max_per_day:
        return False

    # 2. Min cooldown between any two notifications
    last_key = f"leo:notif:last:{profile_id}"
    last_any = redis_client.get(last_key)
    if last_any:
        last_ts = datetime.fromisoformat(last_any.decode() if isinstance(last_any, bytes) else last_any)
        elapsed_h = (datetime.now(timezone.utc) - last_ts).total_seconds() / 3600
        if elapsed_h < min_cooldown_h:
            return False

    # 3. Campaign-specific cooldown
    campaign_key = f"leo:campaign:{rule_id}:{profile_id}:last_sent"
    last_sent = redis_client.get(campaign_key)
    if last_sent:
        last_ts = datetime.fromisoformat(last_sent.decode() if isinstance(last_sent, bytes) else last_sent)
        elapsed_days = (datetime.now(timezone.utc) - last_ts).total_seconds() / 86400
        if elapsed_days < cooldown_days:
            return False

    return True


def record_send(
    redis_client,
    rule_id: str,
    profile_id: str,
    frequency_cap: dict,
) -> None:
    """Record a successful send in Redis for frequency capping."""
    now_iso = datetime.now(timezone.utc).isoformat()
    today_str = date.today().isoformat()
    cooldown_days = frequency_cap.get("cooldown_days", 7)

    pipe = redis_client.pipeline()

    # Campaign cooldown
    campaign_key = f"leo:campaign:{rule_id}:{profile_id}:last_sent"
    pipe.setex(campaign_key, cooldown_days * 86400, now_iso)

    # Global daily counter
    daily_key = f"leo:notif:daily:{profile_id}:{today_str}"
    pipe.incr(daily_key)
    pipe.expire(daily_key, 86400)

    # Last-notification timestamp (for min cooldown gap)
    last_key = f"leo:notif:last:{profile_id}"
    pipe.setex(last_key, CampaignEngineConfigs.MIN_COOLDOWN_HOURS * 3600, now_iso)

    pipe.execute()
