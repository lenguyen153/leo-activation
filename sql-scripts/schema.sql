-- ============================================================
-- AI-Driven Marketing Automation – Core Data Schema
-- PostgreSQL 16
-- Status: Production Ready
-- ============================================================

-- =========================
-- 1. Required Extensions
-- =========================
-- crypto: For gen_random_uuid() and hashing functions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- vector: For AI embeddings (OpenAI/Llama)
CREATE EXTENSION IF NOT EXISTS vector;
-- citext: For case-insensitive email storage
CREATE EXTENSION IF NOT EXISTS citext;

-- =========================
-- 2. Utility Functions
-- =========================
-- Generic function to auto-update 'updated_at' columns
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =========================
-- 3. Tenant Table
-- =========================
CREATE TABLE IF NOT EXISTS tenant (
    tenant_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_name TEXT NOT NULL,
    status      TEXT DEFAULT 'active', -- useful for soft bans
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_tenant_updated_at
BEFORE UPDATE ON tenant
FOR EACH ROW EXECUTE FUNCTION update_timestamp();

-- ============================================================
-- 4. CDP Profiles
-- ============================================================
-- Central table for customer data.
-- Uses JSONB for flexible schema evolution (traits, custom fields).
-- ============================================================

CREATE TABLE IF NOT EXISTS cdp_profiles (
    -- Multi-tenancy Isolation
    tenant_id                UUID NOT NULL REFERENCES tenant(tenant_id) ON DELETE CASCADE,
    
    -- Identity
    profile_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ext_id                   TEXT, -- External ID from CRM/ERP
    
    -- Contact Info (Case Insensitive Email)
    email                    CITEXT,
    landline_number          TEXT,
    mobile_number            TEXT,
    whatsapp_number          TEXT,
    zalo_number              TEXT,
    sms_number               TEXT,

    -- Personal Info
    first_name               TEXT,
    last_name                TEXT,
    job_title                TEXT,
    company_name             TEXT,
    date_of_birth            DATE,

    -- social profiles
    linkedin_url             TEXT,
    facebook_url             TEXT,
    youtube_url             TEXT,
    tiktok_url             TEXT,
    
    -- Metadata
    contact_owner            TEXT,
    contact_timezone         TEXT,

    -- Flexible Data Structures
    working_companies        JSONB, -- e.g. [{ "name": "Corp A", "role": "CEO" }]
    
    -- Segmentation
    segments                 JSONB NOT NULL DEFAULT '[]'::jsonb,
    data_labels              JSONB NOT NULL DEFAULT '[]'::jsonb,
    data_journey_maps        JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Commercial Metrics
    total_lead_score         INTEGER DEFAULT 0,
    clv_score                NUMERIC(12,2) DEFAULT 0.00,
    total_transaction_value  NUMERIC(18,2) DEFAULT 0.00,

    -- Compliance (GDPR/CCPA)
    opt_in                   BOOLEAN DEFAULT FALSE,
    double_opt_in            BOOLEAN DEFAULT FALSE,
    opt_in_metadata          JSONB,

    -- Event Tracking
    last_event_date          DATE,
    
    -- Catch-all for unstructured traits
    raw_attributes           JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Audit
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Constraints
    -- Ensure external ID is unique per tenant
    CONSTRAINT uq_cdp_profile_ext UNIQUE (tenant_id, ext_id)
);

-- CDP Triggers
CREATE TRIGGER trg_cdp_profiles_updated_at
BEFORE UPDATE ON cdp_profiles
FOR EACH ROW EXECUTE FUNCTION update_timestamp();

-- CDP Indexes
-- Standard B-Tree for lookups
CREATE INDEX IF NOT EXISTS idx_cdp_profiles_email ON cdp_profiles (tenant_id, email);
CREATE INDEX IF NOT EXISTS idx_cdp_profiles_mobile ON cdp_profiles (tenant_id, mobile_number);

-- GIN Indexes for high-speed JSONB querying
-- jsonb_path_ops is faster but only supports @> operator (contains)
CREATE INDEX IF NOT EXISTS idx_cdp_profiles_segments 
ON cdp_profiles USING GIN (segments jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_cdp_profiles_labels 
ON cdp_profiles USING GIN (leo_data_labels, cdp_data_labels);

CREATE INDEX IF NOT EXISTS idx_cdp_profiles_raw 
ON cdp_profiles USING GIN (raw_attributes);

-- CDP RLS
ALTER TABLE cdp_profiles ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE polname = 'cdp_profiles_tenant_rls') THEN
        CREATE POLICY cdp_profiles_tenant_rls ON cdp_profiles
        USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
    END IF;
END $$;

-- ============================================================
-- 5. Marketing Event (Partitioned)
-- ============================================================
-- Partitioned by Hash(tenant_id) to distribute high-volume write load.
-- Note: Queries MUST include tenant_id to be efficient.
-- ============================================================
CREATE TABLE IF NOT EXISTS marketing_event (
    tenant_id          UUID NOT NULL REFERENCES tenant(tenant_id) ON DELETE CASCADE,
    
    -- Deterministic Hash ID
    event_id           TEXT NOT NULL, 

    -- Content
    event_name         TEXT NOT NULL,
    event_description  TEXT,
    event_type         TEXT NOT NULL,   -- e.g. 'webinar', 'email'
    event_channel      TEXT NOT NULL,   -- e.g. 'online', 'in-person'

    -- Timing
    start_at           TIMESTAMPTZ NOT NULL,
    end_at             TIMESTAMPTZ NOT NULL,
    timezone           TEXT NOT NULL DEFAULT 'UTC',

    -- Details
    location           TEXT,
    event_url          TEXT,
    campaign_code      TEXT,
    target_audience    TEXT,
    target_segments    JSONB NOT NULL DEFAULT '[]'::jsonb,
    media_assets      JSONB NOT NULL DEFAULT '[]'::jsonb,
    
    -- Finance
    budget_amount      NUMERIC(12,2),
    currency           CHAR(3) DEFAULT 'USD',

    -- Ownership
    owner_team         TEXT,
    owner_email        TEXT,

    -- Lifecycle
    status             TEXT NOT NULL DEFAULT 'planned',

    -- AI / Vector Search
    -- 1536 is standard for OpenAI text-embedding-3-small/ada-002
    embedding          VECTOR(1536),
    embedding_status   TEXT NOT NULL DEFAULT 'pending', -- pending, processed, failed
    embedding_updated_at TIMESTAMPTZ,

    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Partition Key must be part of Primary Key
    CONSTRAINT pk_marketing_event PRIMARY KEY (tenant_id, event_id),
    CONSTRAINT chk_event_time CHECK (end_at >= start_at)

) PARTITION BY HASH (tenant_id);

-- Create Partitions (p0 to p15)
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

-- Event ID Generator (Deterministic Hash)
CREATE OR REPLACE FUNCTION generate_marketing_event_id()
RETURNS TRIGGER AS $$
BEGIN
    -- We use sha256 to create a deterministic ID based on content + time + tenant
    -- This prevents exact duplicates and creates a consistent ID for external ref
    NEW.event_id := encode(digest(lower(concat_ws('||',
            NEW.tenant_id::text,
            NEW.event_name,
            NEW.event_type,
            NEW.event_channel,
            COALESCE(NEW.campaign_code, ''),
            -- Use COALESCE on created_at in case it hasn't settled yet
            COALESCE(NEW.created_at, now())::text 
        )), 'sha256'), 'hex');
    
    -- Ensure updated_at is set
    NEW.updated_at := now();
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Event Triggers
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_event_hash') THEN
        CREATE TRIGGER trg_event_hash
        BEFORE INSERT ON marketing_event
        FOR EACH ROW EXECUTE FUNCTION generate_marketing_event_id();
    END IF;
    
    -- Separate updated_at trigger for updates
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_event_updated_at') THEN
        CREATE TRIGGER trg_event_updated_at
        BEFORE UPDATE ON marketing_event
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
    END IF;
END $$;

-- Event Indexes
CREATE INDEX IF NOT EXISTS idx_event_lookup ON marketing_event (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_event_timeline ON marketing_event (tenant_id, start_at);

-- VECTOR INDEX (HNSW)
-- Changed from IVFFLAT to HNSW. HNSW is better for:
-- 1. Real-time inserts (no training step required).
-- 2. Performance on smaller datasets (starts working immediately).
-- 3. Robustness (IVFFLAT yields 0 results if built on empty table).
CREATE INDEX IF NOT EXISTS idx_event_embedding 
ON marketing_event USING hnsw (embedding vector_cosine_ops);

-- Event RLS
ALTER TABLE marketing_event ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE polname = 'marketing_event_tenant_rls') THEN
        CREATE POLICY marketing_event_tenant_rls ON marketing_event
        USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
    END IF;
END $$;

-- =========================
-- 6. Embedding Job Queue
-- =========================
-- Simple table to act as a queue for Python/Node workers to pick up 
-- text and generate embeddings.
CREATE TABLE IF NOT EXISTS embedding_job (
    job_id      BIGSERIAL PRIMARY KEY,
    tenant_id   UUID NOT NULL,
    event_id    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending', -- pending, processing, completed, failed
    attempts    INTEGER DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at   TIMESTAMPTZ -- used for concurrency locking
);

-- Index for workers to find pending jobs quickly
CREATE INDEX IF NOT EXISTS idx_embedding_job_queue 
ON embedding_job (status, created_at) 
WHERE status = 'pending';

-- Trigger to Enqueue Jobs
CREATE OR REPLACE FUNCTION enqueue_embedding_job()
RETURNS TRIGGER AS $$
BEGIN
    -- Only enqueue if relevant fields changed
    IF (TG_OP = 'INSERT') OR 
       (NEW.event_name IS DISTINCT FROM OLD.event_name) OR 
       (NEW.event_description IS DISTINCT FROM OLD.event_description) THEN
       
       INSERT INTO embedding_job (tenant_id, event_id)
       VALUES (NEW.tenant_id, NEW.event_id);
       
       -- Reset embedding status on the main table
       NEW.embedding_status := 'pending';
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_enqueue_embedding') THEN
        CREATE TRIGGER trg_enqueue_embedding
        BEFORE INSERT OR UPDATE ON marketing_event
        FOR EACH ROW EXECUTE FUNCTION enqueue_embedding_job();
    END IF;
END $$;

-- ============================================================
-- 7. Embedding View (Context Prep)
-- ============================================================
-- Pre-formats the text so the AI worker just queries this view
-- ============================================================
CREATE OR REPLACE VIEW event_content_for_embedding AS
SELECT 
    me.tenant_id,
    me.event_id,
    -- Concatenate fields into a natural language block
    trim(regexp_replace(concat_ws(E'\n\n',
        format('Event Name: %s', initcap(me.event_name)),
        CASE WHEN me.event_description IS NOT NULL AND length(me.event_description) > 0 
             THEN format('Description: %s', me.event_description) END,
        format('Details: Type is %s via %s channel.', me.event_type, me.event_channel),
        CASE WHEN me.target_audience IS NOT NULL 
             THEN format('Target Audience: %s', me.target_audience) END,
        CASE WHEN me.location IS NOT NULL 
             THEN format('Location: %s', me.location) END
    ), '\s+', ' ', 'g')) AS embedding_text
FROM marketing_event me
WHERE me.status <> 'cancelled';