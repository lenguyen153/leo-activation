"""
Campaign Engine Orchestrator
=============================
Entry point: run_campaign_engine()

Pipeline per hourly run:
  1. Load active campaign rules whose schedule matches the current hour
  2. For each rule, build audience SQL from condition tree
  3. Paginate matched profiles in batches
  4. For each profile: freq-cap check → render message → dispatch → log
  5. Write run summary to campaign_engine_runs
"""

import json
import logging
import os
from datetime import date, datetime, timezone

import redis

from data_utils.settings import DatabaseSettings
from main_configs import REDIS_URL, CampaignEngineConfigs

from .circuit_breaker import is_channel_available, record_failure, record_success
from .condition_evaluator import ConditionEvaluator
from .dispatcher import DeliveryStatus, dispatch_message, log_delivery
from .frequency_cap import check_frequency_cap, record_send

logger = logging.getLogger(__name__)


def _should_run_now(cron_expr: str) -> bool:
    """
    Simple check: does the cron schedule match the current hour?
    Supports: '0 * * * *' (every hour), '0 9 * * *' (daily 9am UTC), etc.
    For a full cron parser, swap in croniter.
    """
    try:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return True  # malformed → run anyway to be safe

        minute, hour, dom, month, dow = parts
        now = datetime.now(timezone.utc)

        if minute != "*" and int(minute) != now.minute:
            return False
        if hour != "*" and int(hour) != now.hour:
            return False
        if dom != "*" and int(dom) != now.day:
            return False
        if month != "*" and int(month) != now.month:
            return False
        if dow != "*" and int(dow) != now.weekday():
            return False
        return True
    except (ValueError, IndexError):
        return True


def _load_active_rules(conn, tenant_id: str) -> list[dict]:
    """Fetch all active campaign rules for a tenant."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rule_id, rule_name, conditions, channel, template_id,
                   message_config, frequency_cap, schedule_cron, audience_filter, priority
            FROM campaign_rules
            WHERE tenant_id = %s AND status = 'active'
            ORDER BY priority ASC
            """,
            (tenant_id,),
        )
        return cur.fetchall()


def _load_template(conn, template_id: str) -> dict | None:
    """Load a message template by ID."""
    if not template_id:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT subject_template, body_template, template_engine FROM message_templates WHERE template_id = %s",
            (template_id,),
        )
        return cur.fetchone()


def _build_audience_query(rule: dict) -> tuple[str, dict]:
    """
    Build the full SELECT + WHERE for a rule's audience.
    Returns (sql, params).
    """
    evaluator = ConditionEvaluator()
    where_clause, params = evaluator.to_sql(rule["conditions"])

    # Base query
    select_cols = "p.profile_id, p.primary_email, p.primary_phone, p.first_name, p.identities, p.event_statistics, p.ext_data"

    if evaluator.needs_product_join:
        sql = f"""
            SELECT DISTINCT {select_cols}
            FROM cdp_profiles p
            JOIN product_recommendations pr
              ON p.tenant_id = pr.tenant_id AND p.profile_id = pr.profile_id
            WHERE p.tenant_id = %(tenant_id)s
              AND ({where_clause})
        """
    else:
        sql = f"""
            SELECT {select_cols}
            FROM cdp_profiles p
            WHERE p.tenant_id = %(tenant_id)s
              AND ({where_clause})
        """

    # Audience filter (static segment/score filter)
    audience = rule.get("audience_filter") or {}
    if audience.get("segments"):
        sql += " AND p.segments @> %(af_segments)s::jsonb"
        params["af_segments"] = json.dumps([{"name": s} for s in audience["segments"]])

    sql += " ORDER BY p.profile_id"

    return sql, params


def _drill_down(obj: dict | None, path: str) -> list:
    """Walk a dotted path (e.g. 'ext_data.abandoned_tickers') and return list or []."""
    if not obj:
        return []
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return []
    return cur if isinstance(cur, list) else []


def _render_item_message(message_config: dict, item: dict) -> dict:
    """Apply .format(**item) to title/body/subject strings (for iterate_field rules)."""
    rendered = dict(message_config)
    for k in ("title", "body", "subject"):
        v = rendered.get(k)
        if isinstance(v, str):
            try:
                rendered[k] = v.format(**item)
            except (KeyError, IndexError, ValueError) as e:
                logger.warning("[Engine] Template var missing in %s: %s", k, e)
    return rendered


def _dispatch_for_profile(
    conn, redis_client, rule_id, rule_name, channel, profile,
    message_config, template_row, freq_cap, tenant_id, today_str, stats,
) -> None:
    """Single-shot dispatch (non-iterate rules)."""
    profile_id = profile["profile_id"]

    if redis_client and not check_frequency_cap(redis_client, rule_id, profile_id, freq_cap):
        stats["skipped"] += 1
        return

    if redis_client and not is_channel_available(redis_client, channel):
        stats["skipped"] += 1
        return

    delivery_status, response = dispatch_message(
        channel=channel, profile=profile, message_config=message_config,
        conn=conn, rule_id=rule_id, template_row=template_row,
    )
    log_delivery(conn, tenant_id, rule_id, profile_id, channel,
                 delivery_status.value, response, today_str)

    if delivery_status == DeliveryStatus.SENT:
        if redis_client:
            record_send(redis_client, rule_id, profile_id, freq_cap)
            record_success(redis_client, channel)
        stats["sent"] += 1
    elif delivery_status == DeliveryStatus.RETRY:
        if redis_client:
            record_failure(redis_client, channel)
        stats["errored"] += 1
    else:
        stats["skipped"] += 1


def _dispatch_iterate_for_profile(
    conn, redis_client, rule_id, rule_name, channel, profile,
    message_config, template_row, freq_cap, tenant_id, today_str,
    iterate_path, sub_key_field, stats,
) -> None:
    """Multi-shot dispatch — one send per item in the iterate_field list."""
    profile_id = profile["profile_id"]
    items = _drill_down(profile, iterate_path)
    if not items:
        stats["skipped"] += 1
        return

    for item in items:
        if not isinstance(item, dict):
            continue
        sub_key = str(item.get(sub_key_field, ""))

        if redis_client and not check_frequency_cap(
            redis_client, rule_id, profile_id, freq_cap, sub_key=sub_key
        ):
            stats["skipped"] += 1
            continue

        if redis_client and not is_channel_available(redis_client, channel):
            stats["skipped"] += 1
            continue

        rendered_config = _render_item_message(message_config, item)

        delivery_status, response = dispatch_message(
            channel=channel, profile=profile, message_config=rendered_config,
            conn=conn, rule_id=rule_id, template_row=template_row,
        )
        # Tag delivery log with sub_key so per-ticker history is queryable.
        log_delivery(
            conn, tenant_id, f"{rule_id}:{sub_key}", profile_id, channel,
            delivery_status.value, response, today_str,
        )

        if delivery_status == DeliveryStatus.SENT:
            if redis_client:
                record_send(redis_client, rule_id, profile_id, freq_cap, sub_key=sub_key)
                record_success(redis_client, channel)
            stats["sent"] += 1
        elif delivery_status == DeliveryStatus.RETRY:
            if redis_client:
                record_failure(redis_client, channel)
            stats["errored"] += 1
        else:
            stats["skipped"] += 1


def _process_rule(
    conn,
    redis_client,
    rule: dict,
    tenant_id: str,
    today_str: str,
) -> dict:
    """Evaluate one rule against its audience. Returns per-rule stats."""
    rule_id = str(rule["rule_id"])
    rule_name = rule["rule_name"]
    channel = rule["channel"]
    freq_cap = rule.get("frequency_cap") or {"cooldown_days": 7, "max_per_day": 1}
    message_config = rule.get("message_config") or {}

    stats = {"rule_id": rule_id, "rule_name": rule_name, "matched": 0, "sent": 0, "skipped": 0, "errored": 0}

    # Check circuit breaker before querying audience (skip if Redis unavailable)
    if redis_client and not is_channel_available(redis_client, channel):
        logger.warning("[Engine] Circuit open for channel=%s, skipping rule=%s", channel, rule_name)
        stats["skipped_reason"] = "circuit_open"
        return stats

    # Load template if referenced
    template_row = _load_template(conn, rule.get("template_id"))

    # Build audience query
    try:
        sql, params = _build_audience_query(rule)
        params["tenant_id"] = tenant_id
    except Exception as e:
        logger.error("[Engine] Failed to build query for rule=%s: %s", rule_name, e)
        stats["errored"] = 1
        stats["error"] = str(e)
        return stats

    # Per-ticker (iterate_field) support — e.g. "ext_data.abandoned_tickers"
    iterate_path = message_config.get("iterate_field")
    sub_key_field = message_config.get("iterate_sub_key", "ticker")

    batch_size = CampaignEngineConfigs.BATCH_SIZE
    offset = 0

    while True:
        paginated_sql = f"{sql} LIMIT {batch_size} OFFSET {offset}"
        with conn.cursor() as cur:
            cur.execute(paginated_sql, params)
            rows = cur.fetchall()

        if not rows:
            break

        stats["matched"] += len(rows)

        for profile in rows:
            try:
                if iterate_path:
                    _dispatch_iterate_for_profile(
                        conn, redis_client, rule_id, rule_name, channel, profile,
                        message_config, template_row, freq_cap, tenant_id, today_str,
                        iterate_path, sub_key_field, stats,
                    )
                else:
                    _dispatch_for_profile(
                        conn, redis_client, rule_id, rule_name, channel, profile,
                        message_config, template_row, freq_cap, tenant_id, today_str, stats,
                    )
            except Exception as e:
                logger.error(
                    "[Engine] Rule=%s profile=%s error: %s",
                    rule_name, profile.get("profile_id"), e,
                )
                stats["errored"] += 1

        offset += batch_size

    logger.info(
        "[Engine] Rule=%s done | matched=%d sent=%d skipped=%d errored=%d",
        rule_name, stats["matched"], stats["sent"], stats["skipped"], stats["errored"],
    )
    return stats


def run_campaign_engine(tenant_name: str | None = None) -> dict:
    """
    Main entry point — called by the shell script cronjob.
    Loads rules, evaluates audiences, dispatches messages, logs run.
    """
    settings = DatabaseSettings()
    conn = settings.get_pg_connection()

    try:
        redis_client = redis.from_url(REDIS_URL, socket_connect_timeout=5)
        redis_client.ping()
    except Exception as e:
        logger.warning("[Engine] Redis unavailable (%s) — frequency caps and circuit breaker disabled", e)
        redis_client = None

    target_tenant = tenant_name or os.getenv("TARGET_TENANT", "master")
    today_str = date.today().isoformat()
    run_started = datetime.now(timezone.utc)

    # Resolve tenant
    from agentic_tools.recommendation_system.interest_score import resolve_ids
    try:
        tenant_uuid, _ = resolve_ids(conn, target_tenant, os.getenv("TARGET_SEGMENT", "Active in last 3 months"))
        tenant_id = str(tenant_uuid)
    except Exception as e:
        logger.error("[Engine] Failed to resolve tenant '%s': %s", target_tenant, e)
        conn.close()
        return {"error": str(e)}

    totals = {"rules_evaluated": 0, "profiles_matched": 0, "sent": 0, "skipped": 0, "errored": 0}
    rule_details = []

    try:
        rules = _load_active_rules(conn, tenant_id)
        logger.info("[Engine] Loaded %d active rules for tenant=%s", len(rules), target_tenant)

        for rule in rules:
            # Check if this rule should run at the current time
            if not _should_run_now(rule.get("schedule_cron", "0 * * * *")):
                logger.debug("[Engine] Skipping rule=%s (schedule mismatch)", rule["rule_name"])
                continue

            totals["rules_evaluated"] += 1
            rule_stats = _process_rule(conn, redis_client, rule, tenant_id, today_str)
            rule_details.append(rule_stats)

            totals["profiles_matched"] += rule_stats.get("matched", 0)
            totals["sent"] += rule_stats.get("sent", 0)
            totals["skipped"] += rule_stats.get("skipped", 0)
            totals["errored"] += rule_stats.get("errored", 0)

        # Write run summary
        run_finished = datetime.now(timezone.utc)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO campaign_engine_runs
                    (tenant_id, started_at, finished_at,
                     rules_evaluated, profiles_matched, sent, skipped, errored, run_metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id, run_started, run_finished,
                    totals["rules_evaluated"], totals["profiles_matched"],
                    totals["sent"], totals["skipped"], totals["errored"],
                    json.dumps(rule_details),
                ),
            )
        conn.commit()

        logger.info(
            "[Engine] Run complete | rules=%d matched=%d sent=%d skipped=%d errored=%d | %.1fs",
            totals["rules_evaluated"], totals["profiles_matched"],
            totals["sent"], totals["skipped"], totals["errored"],
            (run_finished - run_started).total_seconds(),
        )

    except Exception as e:
        logger.exception("[Engine] Fatal error in campaign engine run")
        conn.rollback()
        totals["error"] = str(e)

    finally:
        conn.close()

    return totals


# Allow direct invocation: python -m data_workers.campaign_engine.engine
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    result = run_campaign_engine()
    print(json.dumps(result, indent=2))
