"""
CRUD + preview + send endpoints for the Rule-Based Campaign Engine.

Routes:
  POST   /campaigns/rules              — Create new rule
  GET    /campaigns/rules              — List rules (filterable by status)
  GET    /campaigns/rules/{rule_id}    — Get rule detail
  PUT    /campaigns/rules/{rule_id}    — Update rule
  PATCH  /campaigns/rules/{rule_id}/status — Activate / pause / archive
  GET    /campaigns/rules/{rule_id}/runs   — Execution history
  POST   /campaigns/rules/{rule_id}/preview — Dry-run (matched count, no send)
  POST   /campaigns/rules/{rule_id}/send   — Manual trigger (bypasses cron schedule)
"""

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from data_utils.settings import DatabaseSettings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/campaigns", tags=["Campaign Rules"])


# ============================================================
# Pydantic Schemas
# ============================================================

class CampaignRuleCreate(BaseModel):
    rule_name: str
    rule_description: str | None = None
    conditions: dict = Field(..., description="Condition tree (AND/OR/NOT + leaf predicates)")
    channel: str = Field(..., description="push | email | zalo | sms")
    campaign_id: str | None = None
    template_id: str | None = None
    message_config: dict | None = None
    frequency_cap: dict = Field(default={"cooldown_days": 7, "max_per_day": 1})
    schedule_cron: str = Field(default="0 * * * *")
    audience_filter: dict | None = None
    priority: int = 100


class CampaignRuleUpdate(BaseModel):
    rule_name: str | None = None
    rule_description: str | None = None
    conditions: dict | None = None
    channel: str | None = None
    campaign_id: str | None = None
    template_id: str | None = None
    message_config: dict | None = None
    frequency_cap: dict | None = None
    schedule_cron: str | None = None
    audience_filter: dict | None = None
    priority: int | None = None


class StatusUpdate(BaseModel):
    status: str = Field(..., description="active | paused | archived")


class SendRequest(BaseModel):
    background: bool = Field(default=True, description="Run after response (non-blocking). Set false to wait for results.")


# ============================================================
# Helpers
# ============================================================

def _get_conn():
    return DatabaseSettings().get_pg_connection()


def _get_tenant_id(conn) -> str:
    """Resolve default tenant UUID."""
    import os
    target_tenant = os.getenv("TARGET_TENANT", "master")
    with conn.cursor() as cur:
        cur.execute("SELECT tenant_id FROM tenant WHERE tenant_name = %s", (target_tenant,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Tenant '{target_tenant}' not found")
        return str(row["tenant_id"])


# ============================================================
# Routes
# ============================================================

@router.post("/rules", status_code=201)
def create_rule(body: CampaignRuleCreate):
    conn = _get_conn()
    try:
        tenant_id = _get_tenant_id(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO campaign_rules
                    (tenant_id, rule_name, rule_description, conditions, channel,
                     campaign_id, template_id, message_config, frequency_cap,
                     schedule_cron, audience_filter, priority)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING rule_id, created_at
                """,
                (
                    tenant_id, body.rule_name, body.rule_description,
                    json.dumps(body.conditions), body.channel,
                    body.campaign_id, body.template_id,
                    json.dumps(body.message_config) if body.message_config else None,
                    json.dumps(body.frequency_cap),
                    body.schedule_cron,
                    json.dumps(body.audience_filter) if body.audience_filter else None,
                    body.priority,
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return {"rule_id": str(row["rule_id"]), "created_at": str(row["created_at"])}
    finally:
        conn.close()


@router.get("/rules")
def list_rules(status: str | None = Query(None, description="Filter by status")):
    conn = _get_conn()
    try:
        tenant_id = _get_tenant_id(conn)
        sql = "SELECT * FROM campaign_rules WHERE tenant_id = %s"
        params: list = [tenant_id]
        if status:
            sql += " AND status = %s"
            params.append(status)
        sql += " ORDER BY priority ASC, created_at DESC"

        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return {"count": len(rows), "rules": _serialize_rows(rows)}
    finally:
        conn.close()


@router.get("/rules/{rule_id}")
def get_rule(rule_id: UUID):
    conn = _get_conn()
    try:
        tenant_id = _get_tenant_id(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM campaign_rules WHERE rule_id = %s AND tenant_id = %s",
                (str(rule_id), tenant_id),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Rule not found")
        return _serialize_row(row)
    finally:
        conn.close()


@router.put("/rules/{rule_id}")
def update_rule(rule_id: UUID, body: CampaignRuleUpdate):
    conn = _get_conn()
    try:
        tenant_id = _get_tenant_id(conn)
        updates = []
        params = []
        for field_name, value in body.model_dump(exclude_unset=True).items():
            if value is None:
                continue
            if isinstance(value, dict):
                updates.append(f"{field_name} = %s")
                params.append(json.dumps(value))
            else:
                updates.append(f"{field_name} = %s")
                params.append(value)

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        updates.append("updated_at = now()")
        sql = f"UPDATE campaign_rules SET {', '.join(updates)} WHERE rule_id = %s AND tenant_id = %s RETURNING rule_id"
        params.extend([str(rule_id), tenant_id])

        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        conn.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"status": "updated", "rule_id": str(rule_id)}
    finally:
        conn.close()


@router.patch("/rules/{rule_id}/status")
def update_rule_status(rule_id: UUID, body: StatusUpdate):
    if body.status not in ("active", "paused", "archived"):
        raise HTTPException(status_code=400, detail="Status must be active, paused, or archived")

    conn = _get_conn()
    try:
        tenant_id = _get_tenant_id(conn)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE campaign_rules SET status = %s, updated_at = now() WHERE rule_id = %s AND tenant_id = %s RETURNING rule_id",
                (body.status, str(rule_id), tenant_id),
            )
            row = cur.fetchone()
        conn.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"status": body.status, "rule_id": str(rule_id)}
    finally:
        conn.close()


@router.get("/rules/{rule_id}/runs")
def get_rule_runs(rule_id: UUID, limit: int = Query(20, ge=1, le=100)):
    conn = _get_conn()
    try:
        tenant_id = _get_tenant_id(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM campaign_engine_runs
                WHERE tenant_id = %s
                  AND run_metadata::text LIKE %s
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (tenant_id, f"%{rule_id}%", limit),
            )
            rows = cur.fetchall()
        return {"count": len(rows), "runs": _serialize_rows(rows)}
    finally:
        conn.close()


@router.post("/rules/{rule_id}/preview")
def preview_rule(rule_id: UUID):
    """Dry-run: show matched profile count + sample profiles without sending."""
    from data_workers.campaign_engine.condition_evaluator import ConditionEvaluator

    conn = _get_conn()
    try:
        tenant_id = _get_tenant_id(conn)

        # Load rule
        with conn.cursor() as cur:
            cur.execute(
                "SELECT conditions, audience_filter FROM campaign_rules WHERE rule_id = %s AND tenant_id = %s",
                (str(rule_id), tenant_id),
            )
            rule = cur.fetchone()

        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")

        # Build query
        evaluator = ConditionEvaluator()
        where_clause, params = evaluator.to_sql(rule["conditions"])
        params["tenant_id"] = tenant_id

        if evaluator.needs_product_join:
            count_sql = f"""
                SELECT COUNT(DISTINCT p.profile_id) as cnt
                FROM cdp_profiles p
                JOIN product_recommendations pr ON p.tenant_id = pr.tenant_id AND p.profile_id = pr.profile_id
                WHERE p.tenant_id = %(tenant_id)s AND ({where_clause})
            """
            sample_sql = f"""
                SELECT DISTINCT p.profile_id, p.primary_email, p.first_name
                FROM cdp_profiles p
                JOIN product_recommendations pr ON p.tenant_id = pr.tenant_id AND p.profile_id = pr.profile_id
                WHERE p.tenant_id = %(tenant_id)s AND ({where_clause})
                LIMIT 10
            """
        else:
            count_sql = f"""
                SELECT COUNT(*) as cnt FROM cdp_profiles p
                WHERE p.tenant_id = %(tenant_id)s AND ({where_clause})
            """
            sample_sql = f"""
                SELECT p.profile_id, p.primary_email, p.first_name FROM cdp_profiles p
                WHERE p.tenant_id = %(tenant_id)s AND ({where_clause})
                LIMIT 10
            """

        # Audience filter
        audience = rule.get("audience_filter") or {}
        if audience.get("segments"):
            seg_clause = " AND p.segments @> %(af_segments)s::jsonb"
            count_sql += seg_clause
            sample_sql += seg_clause
            params["af_segments"] = json.dumps([{"name": s} for s in audience["segments"]])

        with conn.cursor() as cur:
            cur.execute(count_sql, params)
            count = cur.fetchone()["cnt"]

            cur.execute(sample_sql, params)
            samples = cur.fetchall()

        return {
            "rule_id": str(rule_id),
            "matched_profiles": count,
            "sample_profiles": _serialize_rows(samples),
        }
    finally:
        conn.close()


@router.get("/runs")
def list_runs(limit: int = Query(20, ge=1, le=100)):
    """All recent campaign engine runs across all rules, newest first."""
    conn = _get_conn()
    try:
        tenant_id = _get_tenant_id(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, started_at, finished_at,
                       rules_evaluated, profiles_matched, sent, skipped, errored, run_metadata
                FROM campaign_engine_runs
                WHERE tenant_id = %s
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (tenant_id, limit),
            )
            rows = cur.fetchall()
        return {"count": len(rows), "runs": _serialize_rows(rows)}
    finally:
        conn.close()


@router.get("/rules/{rule_id}/affected")
def get_affected_profiles(
    rule_id: UUID,
    limit: int = Query(200, ge=1, le=1000),
    status: str | None = Query(None, description="Filter by delivery_status: sent | failed | pending_retry"),
):
    """Profiles affected by a specific campaign rule (from delivery_log)."""
    conn = _get_conn()
    try:
        tenant_id = _get_tenant_id(conn)

        sql = """
            SELECT dl.profile_id, dl.channel, dl.delivery_status, dl.sent_at,
                   p.primary_email, p.first_name
            FROM delivery_log dl
            LEFT JOIN cdp_profiles p
                ON dl.tenant_id = p.tenant_id AND dl.profile_id = p.profile_id
            WHERE dl.tenant_id = %s
              AND dl.marketing_event_id LIKE %s
        """
        params: list = [tenant_id, f"campaign_rule_{rule_id}%"]

        if status:
            sql += " AND dl.delivery_status = %s"
            params.append(status)

        sql += " ORDER BY dl.sent_at DESC NULLS LAST LIMIT %s"
        params.append(limit)

        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return {"rule_id": str(rule_id), "count": len(rows), "profiles": _serialize_rows(rows)}
    finally:
        conn.close()


@router.post("/rules/{rule_id}/send", status_code=202)
def send_rule_now(rule_id: UUID, background_tasks: BackgroundTasks, body: SendRequest | None = None):
    """Manually trigger a campaign rule immediately, bypassing cron schedule."""
    from data_workers.campaign_engine.engine import run_single_rule

    conn = _get_conn()
    try:
        tenant_id = _get_tenant_id(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rule_id FROM campaign_rules WHERE rule_id = %s AND tenant_id = %s",
                (str(rule_id), tenant_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Rule not found")
    finally:
        conn.close()

    use_background = body.background if body else True

    if use_background:
        background_tasks.add_task(run_single_rule, str(rule_id))
        return {"status": "queued", "rule_id": str(rule_id)}

    result = run_single_rule(str(rule_id))
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ============================================================
# Serialization helpers
# ============================================================

def _serialize_row(row: dict) -> dict:
    """Convert non-JSON-serializable types to strings."""
    out = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, UUID):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def _serialize_rows(rows: list[dict]) -> list[dict]:
    return [_serialize_row(r) for r in rows]
