-- ============================================================
-- LEO Activation – Core Database Schema
-- PostgreSQL 15+ / 16
-- Status: Production-Approved (AI-native, Multi-tenant)
-- ============================================================


-- =========================
-- 1. REQUIRED EXTENSIONS
-- =========================
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;


-- =========================
-- 2. SHARED UTILITIES
-- =========================

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- =========================
-- 3. TENANT
-- =========================
CREATE TABLE IF NOT EXISTS tenant (
    tenant_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_name TEXT NOT NULL,
    status      TEXT DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_tenant_updated_at'
          AND tgrelid = 'tenant'::regclass
    ) THEN
        CREATE TRIGGER trg_tenant_updated_at
        BEFORE UPDATE ON tenant
        FOR EACH ROW
        EXECUTE FUNCTION update_timestamp();
    END IF;
END $$;



-- ============================================================
-- 4. CDP PROFILES
-- ============================================================
CREATE TABLE IF NOT EXISTS cdp_profiles (
    tenant_id       UUID NOT NULL REFERENCES tenant(tenant_id) ON DELETE CASCADE,
    profile_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ext_id          TEXT,

    email           CITEXT,
    mobile_number   TEXT,
    zalo_number     TEXT,

    first_name      TEXT,
    last_name       TEXT,
    job_title       TEXT,
    company_name    TEXT,

    segments        JSONB NOT NULL DEFAULT '[]'::jsonb,
    data_labels     JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Denormalized, append-only snapshot refs
    segment_snapshots JSONB NOT NULL DEFAULT '[]'::jsonb,

    raw_attributes  JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_cdp_profile_ext UNIQUE (tenant_id, ext_id)
);



DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_cdp_profiles_updated_at'
          AND tgrelid = 'cdp_profiles'::regclass
    ) THEN
        CREATE TRIGGER trg_cdp_profiles_updated_at
        BEFORE UPDATE ON cdp_profiles
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
    END IF;
END $$;



-- Append-only guard for segment_snapshots
CREATE OR REPLACE FUNCTION prevent_snapshot_removal()
RETURNS TRIGGER AS $$
BEGIN
    IF jsonb_array_length(NEW.segment_snapshots)
       < jsonb_array_length(OLD.segment_snapshots) THEN
        RAISE EXCEPTION 'segment_snapshots is append-only';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_prevent_snapshot_removal'
          AND tgrelid = 'cdp_profiles'::regclass
    ) THEN
        CREATE TRIGGER trg_prevent_snapshot_removal
        BEFORE UPDATE ON cdp_profiles
        FOR EACH ROW
        EXECUTE FUNCTION prevent_snapshot_removal();
    END IF;
END $$;


-- Indexes
CREATE INDEX IF NOT EXISTS idx_cdp_profiles_email
ON cdp_profiles (tenant_id, email);

CREATE INDEX IF NOT EXISTS idx_cdp_profiles_segments
ON cdp_profiles USING GIN (segments jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_cdp_profiles_segment_snapshots
ON cdp_profiles USING GIN (segment_snapshots jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_cdp_profiles_raw
ON cdp_profiles USING GIN (raw_attributes);

-- RLS
ALTER TABLE cdp_profiles ENABLE ROW LEVEL SECURITY;

-- Create RLS policy if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE policyname = 'cdp_profiles_tenant_rls'
          AND schemaname = current_schema()
          AND tablename = 'cdp_profiles'
    ) THEN
        CREATE POLICY cdp_profiles_tenant_rls
        ON cdp_profiles
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        );
    END IF;
END $$;




-- ============================================================
-- 5. CAMPAIGN (STRATEGY)
-- ============================================================
CREATE TABLE IF NOT EXISTS campaign (
    tenant_id      UUID NOT NULL REFERENCES tenant(tenant_id) ON DELETE CASCADE,
    campaign_id    UUID NOT NULL DEFAULT gen_random_uuid(),

    campaign_code  TEXT NOT NULL,
    campaign_name  TEXT NOT NULL,

    objective      TEXT,
    status         TEXT NOT NULL DEFAULT 'active',

    start_at       TIMESTAMPTZ,
    end_at         TIMESTAMPTZ,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_campaign PRIMARY KEY (tenant_id, campaign_id),
    CONSTRAINT uq_campaign_code UNIQUE (tenant_id, campaign_code),
    CONSTRAINT chk_campaign_time CHECK (
        end_at IS NULL OR start_at IS NULL OR end_at >= start_at
    )
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_campaign_updated_at'
          AND tgrelid = 'campaign'::regclass
    ) THEN
        CREATE TRIGGER trg_campaign_updated_at
        BEFORE UPDATE ON campaign
        FOR EACH ROW
        EXECUTE FUNCTION update_timestamp();
    END IF;
END $$;


ALTER TABLE campaign ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE policyname = 'campaign_tenant_rls'
          AND schemaname = current_schema()
          AND tablename = 'campaign'
    ) THEN
        CREATE POLICY campaign_tenant_rls
        ON campaign
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        );
    END IF;
END $$;



-- ============================================================
-- 6. MARKETING EVENT (EXECUTION DEFINITION)
-- ============================================================
CREATE TABLE IF NOT EXISTS marketing_event (
    tenant_id      UUID NOT NULL REFERENCES tenant(tenant_id) ON DELETE CASCADE,
    event_id       TEXT NOT NULL,

    campaign_id    UUID,

    event_name     TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    event_channel  TEXT NOT NULL,

    start_at       TIMESTAMPTZ NOT NULL,
    end_at         TIMESTAMPTZ NOT NULL,

    status         TEXT NOT NULL DEFAULT 'planned',

    embedding      VECTOR(1536),
    embedding_status TEXT NOT NULL DEFAULT 'pending',

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_marketing_event PRIMARY KEY (tenant_id, event_id),

    CONSTRAINT fk_marketing_event_campaign
        FOREIGN KEY (tenant_id, campaign_id)
        REFERENCES campaign (tenant_id, campaign_id)
        ON DELETE SET NULL,

    CONSTRAINT chk_event_time CHECK (end_at >= start_at)
) PARTITION BY HASH (tenant_id);

-- Partitions
DO $$
BEGIN
    FOR i IN 0..15 LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS marketing_event_p%s
             PARTITION OF marketing_event
             FOR VALUES WITH (MODULUS 16, REMAINDER %s);',
            i, i
        );
    END LOOP;
END $$;

-- Deterministic event_id
CREATE OR REPLACE FUNCTION generate_marketing_event_id()
RETURNS TRIGGER AS $$
BEGIN
    NEW.event_id := encode(
        digest(
            lower(concat_ws('||',
                NEW.tenant_id::text,
                NEW.event_name,
                NEW.event_type,
                NEW.event_channel,
                COALESCE(NEW.created_at, now())::text
            )),
            'sha256'
        ),
        'hex'
    );
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_marketing_event_hash'
          AND tgrelid = 'marketing_event'::regclass
    ) THEN
        CREATE TRIGGER trg_marketing_event_hash
        BEFORE INSERT ON marketing_event
        FOR EACH ROW
        EXECUTE FUNCTION generate_marketing_event_id();
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_marketing_event_updated_at'
          AND tgrelid = 'marketing_event'::regclass
    ) THEN
        CREATE TRIGGER trg_marketing_event_updated_at
        BEFORE UPDATE ON marketing_event
        FOR EACH ROW
        EXECUTE FUNCTION update_timestamp();
    END IF;
END $$;


CREATE INDEX IF NOT EXISTS idx_marketing_event_status
ON marketing_event (tenant_id, status);

-- NOTE: HNSW indexes SHOULD be created per-partition in production

ALTER TABLE marketing_event ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE policyname = 'marketing_event_tenant_rls'
          AND schemaname = current_schema()
          AND tablename = 'marketing_event'
    ) THEN
        CREATE POLICY marketing_event_tenant_rls
        ON marketing_event
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        );
    END IF;
END $$;



-- ============================================================
-- 7. SEGMENT SNAPSHOT (IMMUTABLE METADATA)
-- ============================================================
CREATE TABLE IF NOT EXISTS segment_snapshot (
    tenant_id        UUID NOT NULL REFERENCES tenant(tenant_id) ON DELETE CASCADE,
    snapshot_id      UUID NOT NULL DEFAULT gen_random_uuid(),

    segment_name     TEXT NOT NULL,
    segment_version  TEXT,
    snapshot_reason  TEXT,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_segment_snapshot
        PRIMARY KEY (tenant_id, snapshot_id)
);

ALTER TABLE segment_snapshot ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE policyname = 'segment_snapshot_tenant_rls'
          AND schemaname = current_schema()
          AND tablename = 'segment_snapshot'
    ) THEN
        CREATE POLICY segment_snapshot_tenant_rls
        ON segment_snapshot
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        );
    END IF;
END $$;



-- ============================================================
-- 8. SEGMENT SNAPSHOT MEMBERS (SCALE SAFE)
-- ============================================================
CREATE TABLE IF NOT EXISTS segment_snapshot_member (
    tenant_id    UUID NOT NULL REFERENCES tenant(tenant_id) ON DELETE CASCADE,
    snapshot_id  UUID NOT NULL,
    profile_id   UUID NOT NULL,

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_segment_snapshot_member
        PRIMARY KEY (tenant_id, snapshot_id, profile_id),

    CONSTRAINT fk_snapshot_member_snapshot
        FOREIGN KEY (tenant_id, snapshot_id)
        REFERENCES segment_snapshot (tenant_id, snapshot_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_snapshot_member_profile
        FOREIGN KEY (profile_id)
        REFERENCES cdp_profiles (profile_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_snapshot_member_profile
ON segment_snapshot_member (tenant_id, profile_id);

ALTER TABLE segment_snapshot_member ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE policyname = 'segment_snapshot_member_tenant_rls'
          AND schemaname = current_schema()
          AND tablename = 'segment_snapshot_member'
    ) THEN
        CREATE POLICY segment_snapshot_member_tenant_rls
        ON segment_snapshot_member
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        );
    END IF;
END $$;



-- ============================================================
-- 9. AGENT TASK (AI DECISION TRACE)
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_task (
    tenant_id    UUID NOT NULL REFERENCES tenant(tenant_id) ON DELETE CASCADE,
    task_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    agent_name   TEXT NOT NULL,
    task_type    TEXT NOT NULL,
    task_goal    TEXT,

    campaign_id  UUID,
    event_id     TEXT,
    snapshot_id  UUID,

    reasoning_summary TEXT,
    reasoning_trace   JSONB,

    status       TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,

    CONSTRAINT fk_agent_task_campaign
        FOREIGN KEY (tenant_id, campaign_id)
        REFERENCES campaign (tenant_id, campaign_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_agent_task_event
        FOREIGN KEY (tenant_id, event_id)
        REFERENCES marketing_event (tenant_id, event_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_agent_task_snapshot
        FOREIGN KEY (tenant_id, snapshot_id)
        REFERENCES segment_snapshot (tenant_id, snapshot_id)
        ON DELETE SET NULL
);

ALTER TABLE agent_task ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE policyname = 'agent_task_tenant_rls'
          AND schemaname = current_schema()
          AND tablename = 'agent_task'
    ) THEN
        CREATE POLICY agent_task_tenant_rls
        ON agent_task
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        );
    END IF;
END $$;



-- ============================================================
-- 10. DELIVERY LOG (EXECUTION TRUTH)
-- ============================================================
CREATE TABLE IF NOT EXISTS delivery_log (
    tenant_id     UUID NOT NULL REFERENCES tenant(tenant_id) ON DELETE CASCADE,
    delivery_id   BIGSERIAL PRIMARY KEY,

    campaign_id   UUID,
    event_id      TEXT NOT NULL,
    profile_id    UUID NOT NULL,
    snapshot_id   UUID,

    channel       TEXT NOT NULL,
    destination   TEXT,

    delivery_status TEXT NOT NULL,
    provider_response JSONB,

    sent_at       TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_delivery_event
        FOREIGN KEY (tenant_id, event_id)
        REFERENCES marketing_event (tenant_id, event_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_delivery_profile
        FOREIGN KEY (profile_id)
        REFERENCES cdp_profiles (profile_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_delivery_snapshot
        FOREIGN KEY (tenant_id, snapshot_id)
        REFERENCES segment_snapshot (tenant_id, snapshot_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_delivery_log_event
ON delivery_log (tenant_id, event_id, delivery_status);

CREATE INDEX IF NOT EXISTS idx_delivery_log_profile
ON delivery_log (tenant_id, profile_id);

ALTER TABLE delivery_log ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE policyname = 'delivery_log_tenant_rls'
          AND schemaname = current_schema()
          AND tablename = 'delivery_log'
    ) THEN
        CREATE POLICY delivery_log_tenant_rls
        ON delivery_log
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)::uuid
        );
    END IF;
END $$;


-- ============================================================
-- 6. Embedding Job Queue
-- ============================================================
CREATE TABLE IF NOT EXISTS embedding_job (
    job_id      BIGSERIAL PRIMARY KEY,
    tenant_id   UUID NOT NULL,
    event_id    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    attempts    INTEGER DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_embedding_job_queue
ON embedding_job (status, created_at)
WHERE status = 'pending';

CREATE OR REPLACE FUNCTION enqueue_embedding_job()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT'
       OR NEW.event_name IS DISTINCT FROM OLD.event_name
       OR NEW.event_description IS DISTINCT FROM OLD.event_description THEN

        INSERT INTO embedding_job (tenant_id, event_id)
        VALUES (NEW.tenant_id, NEW.event_id);

        NEW.embedding_status := 'pending';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enqueue_embedding
BEFORE INSERT OR UPDATE ON marketing_event
FOR EACH ROW EXECUTE FUNCTION enqueue_embedding_job();

-- ============================================================


