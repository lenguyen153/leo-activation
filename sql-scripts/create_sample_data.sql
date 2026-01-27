-- ============================================================
-- SAMPLE TEST DATA GENERATION
-- System: LEO Activation
-- Purpose: Generate Tenants, Profiles, Assets, News, Graph Data
-- Idempotency: Safe to re-run
-- ============================================================

-- ============================================================
-- 1. EXTENSIONS & SEARCH PATH
-- ============================================================
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- ============================================================
-- A. RELATIONAL DATA
-- ============================================================

-- ------------------------------------------------------------
-- 1. Tenant
-- ------------------------------------------------------------
INSERT INTO tenant (
    tenant_id,
    tenant_name,
    status,
    keycloak_realm,
    keycloak_client_id
)
VALUES (
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'Alpha Investment Fund',
    'active',
    'leo-prod',
    'leo-activation'
)
ON CONFLICT (tenant_id) DO UPDATE
SET
    tenant_name        = EXCLUDED.tenant_name,
    status             = EXCLUDED.status,
    keycloak_realm     = EXCLUDED.keycloak_realm,
    keycloak_client_id = EXCLUDED.keycloak_client_id,
    updated_at         = now();

-- ------------------------------------------------------------
-- 2. CDP Profiles (schema-correct JSONB)
-- ------------------------------------------------------------
INSERT INTO cdp_profiles (
    tenant_id,
    profile_id,
    primary_email,
    first_name,
    last_name,
    segments,
    journey_maps
)
VALUES
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    '00000000-0000-0000-0000-000000000001',
    'alice.tech@test.com',
    'Alice',
    'TechFan',
    '[
        { "id": "HIGH_GROWTH", "name": "High Growth Investor" },
        { "id": "TECH", "name": "Technology Focus" }
     ]'::jsonb,
    '[
        { "id": "J01", "name": "Investor Onboarding", "funnelIndex": 1 }
     ]'::jsonb
),
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    '00000000-0000-0000-0000-000000000002',
    'bob.safe@test.com',
    'Bob',
    'Conservative',
    '[
        { "id": "DIVIDEND", "name": "Dividend Investor" },
        { "id": "RETIREMENT", "name": "Retirement Planning" }
     ]'::jsonb,
    '[
        { "id": "J01", "name": "Investor Onboarding", "funnelIndex": 2 }
     ]'::jsonb
),
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    '00000000-0000-0000-0000-000000000003',
    'charlie.crypto@test.com',
    'Charlie',
    'Degen',
    '[
        { "id": "CRYPTO", "name": "Crypto Investor" },
        { "id": "HIGH_RISK", "name": "High Risk Appetite" }
     ]'::jsonb,
    '[
        { "id": "J02", "name": "Advanced Trading", "funnelIndex": 3 }
     ]'::jsonb
),
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    '00000000-0000-0000-0000-000000000004',
    'david.trader@test.com',
    'David',
    'DayTrader',
    '[
        { "id": "FOREX", "name": "Forex Trader" },
        { "id": "ACTIVE", "name": "Active Trading" }
     ]'::jsonb,
    '[
        { "id": "J02", "name": "Advanced Trading", "funnelIndex": 2 }
     ]'::jsonb
),
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    '00000000-0000-0000-0000-000000000005',
    'eve.energy@test.com',
    'Eve',
    'OilBaron',
    '[
        { "id": "ENERGY", "name": "Energy Investor" },
        { "id": "COMMODITIES", "name": "Commodity Focus" }
     ]'::jsonb,
    '[
        { "id": "J01", "name": "Investor Onboarding", "funnelIndex": 1 }
     ]'::jsonb
)
ON CONFLICT (profile_id) DO UPDATE
SET
    segments      = EXCLUDED.segments,
    journey_maps  = EXCLUDED.journey_maps,
    updated_at    = now();

-- ------------------------------------------------------------
-- 3. Instruments
-- ------------------------------------------------------------
INSERT INTO instruments (tenant_id, symbol, name, type, sector)
VALUES
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11','AAPL','Apple Inc.','STOCK','Technology'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11','MSFT','Microsoft Corp.','STOCK','Technology'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11','BTC','Bitcoin','CRYPTO','Crypto'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11','XOM','Exxon Mobil','STOCK','Energy')
ON CONFLICT (tenant_id, symbol) DO UPDATE
SET
    name       = EXCLUDED.name,
    sector     = EXCLUDED.sector,
    updated_at = now();

-- ------------------------------------------------------------
-- 4. News Feed
-- ------------------------------------------------------------
INSERT INTO news_feed (
    tenant_id,
    title,
    related_symbols,
    sentiment_score,
    published_at
)
VALUES
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11','Fed Announces Rate Hike',ARRAY['EURUSD','GOLD'],-0.5,now()),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11','Apple Releases iPhone',ARRAY['AAPL'],0.8,now()),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11','Bitcoin Halving Approaches',ARRAY['BTC'],0.9,now())
ON CONFLICT DO NOTHING;

-- ============================================================
-- B. GRAPH DATA (APACHE AGE)
-- ============================================================

-- ------------------------------------------------------------
-- 1. Create Graph
-- ------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'investing_knowledge_graph'
    ) THEN
        PERFORM ag_catalog.create_graph('investing_knowledge_graph');
    END IF;
END $$;

-- ------------------------------------------------------------
-- 2. Users
-- ------------------------------------------------------------
SELECT * FROM ag_catalog.cypher('investing_knowledge_graph', $$
    MERGE (:User {id:'00000000-0000-0000-0000-000000000001',name:'Alice'})
    MERGE (:User {id:'00000000-0000-0000-0000-000000000002',name:'Bob'})
    MERGE (:User {id:'00000000-0000-0000-0000-000000000003',name:'Charlie'})
$$) AS (v agtype);

-- ------------------------------------------------------------
-- 3. Sectors & Assets
-- ------------------------------------------------------------
SELECT * FROM ag_catalog.cypher('investing_knowledge_graph', $$
    MERGE (:Sector {name:'Technology'})
    MERGE (:Sector {name:'Energy'})
    MERGE (:Sector {name:'Crypto'})

    MERGE (a:Asset {symbol:'AAPL'})-[:BELONGS_TO]->(:Sector {name:'Technology'})
    MERGE (b:Asset {symbol:'BTC'})-[:BELONGS_TO]->(:Sector {name:'Crypto'})
    MERGE (x:Asset {symbol:'XOM'})-[:BELONGS_TO]->(:Sector {name:'Energy'})
$$) AS (v agtype);

-- ------------------------------------------------------------
-- 4. Holdings
-- ------------------------------------------------------------
SELECT * FROM ag_catalog.cypher('investing_knowledge_graph', $$
    MATCH (u:User {name:'Alice'}),(a:Asset {symbol:'AAPL'})
    MERGE (u)-[:HOLDS]->(a)
$$) AS (v agtype);

-- ============================================================
-- C. MANUAL ALERT TEST
-- ============================================================

INSERT INTO alert_rules (
    tenant_id,
    profile_id,
    symbol,
    alert_type,
    condition_logic,
    status
)
VALUES (
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    '00000000-0000-0000-0000-000000000001',
    'AAPL',
    'PRICE',
    '{"operator": ">", "value": 150}'::jsonb,
    'ACTIVE'
)
ON CONFLICT DO NOTHING;

INSERT INTO market_snapshot (symbol, price)
VALUES ('AAPL', 155.00)
ON CONFLICT (symbol) DO UPDATE
SET price = EXCLUDED.price,
    last_updated = now();

DO $$
BEGIN
    RAISE NOTICE 'Test data generation completed successfully.';
END $$;
