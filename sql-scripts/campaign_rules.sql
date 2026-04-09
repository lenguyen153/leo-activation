-- ============================================================
-- Rule-Based Notification Campaign Engine — DDL
-- ============================================================

-- 1. Campaign Rules
CREATE TABLE IF NOT EXISTS campaign_rules (
    rule_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenant(tenant_id) ON DELETE CASCADE,
    campaign_id     VARCHAR,

    rule_name       VARCHAR NOT NULL,
    rule_description TEXT,
    status          VARCHAR NOT NULL DEFAULT 'paused',   -- active | paused | archived
    priority        INT DEFAULT 100,                     -- lower = higher priority

    -- Rule definition (composable condition tree)
    conditions      JSONB NOT NULL,
    channel         VARCHAR NOT NULL,                    -- push | email | zalo | sms
    template_id     UUID REFERENCES message_templates(template_id) ON DELETE SET NULL,
    message_config  JSONB,                               -- fallback: {subject, body, topic_type}

    -- Scheduling & frequency
    frequency_cap   JSONB DEFAULT '{"cooldown_days": 7, "max_per_day": 1}',
    schedule_cron   VARCHAR DEFAULT '0 * * * *',         -- 5-field cron expression
    audience_filter JSONB,                               -- static filters: {segments, min_score}

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_campaign_rules_tenant_status
    ON campaign_rules (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_campaign_rules_priority
    ON campaign_rules (tenant_id, priority);


-- 2. Engine Run Audit Log
CREATE TABLE IF NOT EXISTS campaign_engine_runs (
    run_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenant(tenant_id) ON DELETE CASCADE,
    started_at       TIMESTAMPTZ NOT NULL,
    finished_at      TIMESTAMPTZ,

    rules_evaluated  INT DEFAULT 0,
    profiles_matched INT DEFAULT 0,
    sent             INT DEFAULT 0,
    skipped          INT DEFAULT 0,
    errored          INT DEFAULT 0,
    run_metadata     JSONB                               -- per-rule breakdown
);

CREATE INDEX IF NOT EXISTS idx_engine_runs_tenant_time
    ON campaign_engine_runs (tenant_id, started_at);
