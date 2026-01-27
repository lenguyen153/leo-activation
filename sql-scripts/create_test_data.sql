-- ============================================================
-- LEO DATA ACTIVATION - IDEMPOTENT SAMPLE DATA GENERATOR (v3)
-- Fixed: Handles PRIMARY KEY conflict on Tenant ID
-- ============================================================

-- ------------------------------------------------------------
-- 1. SETUP TENANT (Fixed)
-- ------------------------------------------------------------
INSERT INTO tenant (tenant_id, tenant_name, keycloak_realm, keycloak_client_id)
VALUES (
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 
    'LEO-SAMPLE-TENANT', 
    'leo-sample', 
    'leo-activation'
) 
ON CONFLICT (tenant_id) -- Target the UUID Primary Key
DO UPDATE SET 
    status = 'active',
    tenant_name = EXCLUDED.tenant_name;

-- Set Session Tenant for RLS
SELECT set_config('app.current_tenant_id', 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', false);

-- ------------------------------------------------------------
-- 2. CREATE USERS (CDP PROFILES)
-- ------------------------------------------------------------
INSERT INTO cdp_profiles (
    tenant_id, profile_id, first_name, last_name, primary_email, media_channels, ext_data
) VALUES 
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'p_alice', 'Alice', 'Smith', 'alice@test.com', 
    '["EMAIL", "WEB_PUSH"]'::jsonb, 
    '{"web_push_token": "token_alice_x8z", "device": "macbook_pro"}'::jsonb
),
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'p_bob', 'Bob', 'Jones', 'bob@test.com', 
    '["EMAIL"]'::jsonb, '{}'
),
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'p_charlie', 'Charlie', 'Day', 'charlie@test.com', 
    '["SMS"]'::jsonb, '{}'
)
ON CONFLICT (tenant_id, profile_id) 
DO UPDATE SET 
    media_channels = EXCLUDED.media_channels,
    ext_data = EXCLUDED.ext_data,
    updated_at = now();

-- Filler Users (Avoid duplicates via DO NOTHING)
INSERT INTO cdp_profiles (tenant_id, profile_id, first_name, primary_email)
SELECT 
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'p_user_' || s,
    'User' || s,
    'user' || s || '@test.com'
FROM generate_series(4, 10) as s
ON CONFLICT (tenant_id, profile_id) DO NOTHING;

-- ------------------------------------------------------------
-- 3. CONSENT MANAGEMENT
-- ------------------------------------------------------------
INSERT INTO consent_management (tenant_id, profile_id, channel, is_allowed, legal_basis)
VALUES 
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'p_alice', 'EMAIL', true, 'legitimate_interest'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'p_alice', 'WEB_PUSH', true, 'consent_form')
ON CONFLICT (tenant_id, profile_id, channel) 
DO UPDATE SET 
    is_allowed = EXCLUDED.is_allowed,
    updated_at = now();

-- ------------------------------------------------------------
-- 4. ASSETS (INSTRUMENTS)
-- ------------------------------------------------------------
INSERT INTO instruments (tenant_id, symbol, name, type, sector)
VALUES 
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'AAPL', 'Apple Inc.', 'STOCK', 'Technology'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'GOOGL', 'Alphabet Inc.', 'STOCK', 'Technology'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'MSFT', 'Microsoft', 'STOCK', 'Technology'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'TSLA', 'Tesla', 'STOCK', 'Consumer Discretionary'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'BTC-USD', 'Bitcoin', 'CRYPTO', 'Currency'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'ETH-USD', 'Ethereum', 'CRYPTO', 'Smart Contract')
ON CONFLICT (tenant_id, symbol) 
DO UPDATE SET 
    name = EXCLUDED.name,
    sector = EXCLUDED.sector,
    type = EXCLUDED.type;

-- Filler Assets
INSERT INTO instruments (tenant_id, symbol, name, type)
SELECT 
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'SYM-' || s,
    'Sample Asset ' || s,
    'STOCK'
FROM generate_series(7, 20) as s
ON CONFLICT (tenant_id, symbol) DO NOTHING;

-- Market Snapshot
INSERT INTO market_snapshot (symbol, price, last_updated)
VALUES 
('AAPL', 145.00, NOW() - interval '1 hour'),
('BTC-USD', 48000.00, NOW()),
('GOOGL', 2800.00, NOW())
ON CONFLICT (symbol) DO UPDATE 
SET price = EXCLUDED.price, last_updated = NOW();

-- ------------------------------------------------------------
-- 5. ALERT RULES
-- ------------------------------------------------------------
INSERT INTO alert_rules (tenant_id, profile_id, symbol, alert_type, condition_logic, status)
VALUES 
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 
    'p_alice', 
    'AAPL', 
    'PRICE', 
    '{"operator": ">", "value": 155.00}'::jsonb, 
    'ACTIVE'
),
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 
    'p_bob', 
    'BTC-USD', 
    'PRICE', 
    '{"operator": "<", "value": 45000.00}'::jsonb, 
    'ACTIVE'
)
ON CONFLICT (tenant_id, rule_id) 
DO UPDATE SET status = EXCLUDED.status;

-- ------------------------------------------------------------
-- 6. MESSAGE TEMPLATES
-- ------------------------------------------------------------
INSERT INTO message_templates (tenant_id, channel, template_name, subject_template, body_template, status)
VALUES 
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'email',
    'price_alert_default',
    'Alert: {{ symbol }} reached {{ current_price }}',
    '<p>Hi {{ first_name }},</p><p>{{ symbol }} has just crossed your target of {{ target_price }}. Current price is <strong>{{ current_price }}</strong>.</p>',
    'approved'
),
(
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'web_push',
    'price_alert_push',
    '{{ symbol }} Price Alert',
    '{{ symbol }} is now {{ current_price }}. Tap to trade.',
    'approved'
)
ON CONFLICT (tenant_id, channel, template_name, version) 
DO UPDATE SET 
    body_template = EXCLUDED.body_template,
    updated_at = now();

-- ------------------------------------------------------------
-- 7. GRAPH DATA (Apache AGE)
-- ------------------------------------------------------------
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Initialize Graph (Safe to run if exists)
SELECT create_graph('investing_knowledge_graph') 
WHERE NOT EXISTS (SELECT 1 FROM ag_graph WHERE name = 'investing_knowledge_graph');

-- Merge Nodes (Vertices)
SELECT * FROM cypher('investing_knowledge_graph', $$
    MERGE (u:User {id: 'p_alice'}) 
    SET u.name = 'Alice', u.type = 'investor'

    MERGE (b:User {id: 'p_bob'}) 
    SET b.name = 'Bob', b.type = 'trader'
    
    MERGE (a1:Asset {symbol: 'AAPL'}) SET a1.name = 'Apple Inc.'
    MERGE (a2:Asset {symbol: 'TSLA'}) SET a2.name = 'Tesla'
    MERGE (a3:Asset {symbol: 'BTC-USD'}) SET a3.name = 'Bitcoin'
    
    MERGE (s1:Sector {name: 'Technology'})
    MERGE (s2:Sector {name: 'Automotive'})
    
    MERGE (n:NewsEvent {id: 5}) 
    SET n.title = 'Tech Regulation Update', n.sentiment = -0.5
$$) as (a agtype);

-- Merge Edges (Relationships)
SELECT * FROM cypher('investing_knowledge_graph', $$
    MATCH (u:User {name: 'Alice'}), (a:Asset {symbol: 'AAPL'})
    MERGE (u)-[r:HOLDS]->(a)
    SET r.quantity = 50
$$) as (a agtype);

SELECT * FROM cypher('investing_knowledge_graph', $$
    MATCH (u:User {name: 'Bob'}), (a:Asset {symbol: 'BTC-USD'})
    MERGE (u)-[r:HOLDS]->(a)
    SET r.quantity = 1.5
$$) as (a agtype);

-- Link Assets to Sectors
SELECT * FROM cypher('investing_knowledge_graph', $$
    MATCH (a:Asset {symbol: 'AAPL'}), (s:Sector {name: 'Technology'})
    MERGE (a)-[:BELONGS_TO]->(s)
$$) as (a agtype);

-- Link News to Sector
SELECT * FROM cypher('investing_knowledge_graph', $$
    MATCH (n:NewsEvent {id: 5}), (s:Sector {name: 'Technology'})
    MERGE (n)-[r:IMPACTS]->(s)
    SET r.confidence = 0.9
$$) as (a agtype);