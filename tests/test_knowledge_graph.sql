-- =========================================================
-- LEO CDP: Unified Knowledge Graph (Apache AGE 1.6)
-- Purpose:
--   - Single graph mixing people, companies, assets, places, content
--   - Designed to test reasoning queries, not just CRUD
-- =========================================================


-- load Apache AGE for Graph features
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- ---------------------------------------------------------
-- Create graph once
-- ---------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'social_graph'
  ) THEN
    PERFORM create_graph('social_graph');
  END IF;
END
$$;

-- ---------------------------------------------------------
-- Insert Nodes (Profiles)
-- ---------------------------------------------------------
SELECT * FROM cypher('social_graph', $$
MERGE (:Profile {profile_key:'u_001', name:'Alice', profile_type:'person', city:'HCMC'})
MERGE (:Profile {profile_key:'u_002', name:'Bob', profile_type:'person', city:'New York'})
MERGE (:Profile {profile_key:'u_003', name:'Charlie', profile_type:'person', city:'London'})
MERGE (:Profile {profile_key:'u_004', name:'Diana', profile_type:'person', city:'Singapore'})
MERGE (:Profile {profile_key:'u_005', name:'Ethan', profile_type:'person', city:'Berlin'})

MERGE (:Profile {profile_key:'c_001', name:'TechCorp', profile_type:'company', industry:'AI'})
MERGE (:Profile {profile_key:'c_002', name:'GreenEnergy', profile_type:'company', industry:'Renewables'})
MERGE (:Profile {profile_key:'c_003', name:'FinBank', profile_type:'company', industry:'Finance'})

MERGE (:Profile {profile_key:'s_001', name:'NVDA', profile_type:'stock', sector:'Semiconductors'})
MERGE (:Profile {profile_key:'s_002', name:'TSLA', profile_type:'stock', sector:'Automotive'})
MERGE (:Profile {profile_key:'s_003', name:'BTC', profile_type:'stock', sector:'Crypto'})
MERGE (:Profile {profile_key:'s_004', name:'AAPL', profile_type:'stock', sector:'Consumer Tech'})
MERGE (:Profile {profile_key:'s_005', name:'VNM', profile_type:'stock', sector:'Vietnam ETF'})

MERGE (:Profile {profile_key:'b_001', name:'Clean Code', profile_type:'book'})
MERGE (:Profile {profile_key:'b_002', name:'Psychology of Money', profile_type:'book'})
$$) AS (v agtype);

-- ---------------------------------------------------------
-- Insert Nodes (Segments of LEO CDP)
-- Improvements:
--  • Add segment_type (behavioral, lifecycle, value, rule-based)
--  • Add is_dynamic (agent can reason if membership changes)
--  • Add definition (human + agent readable logic hint)
--  • totalCount is kept but treated as snapshot / optional
-- ---------------------------------------------------------
SELECT * FROM cypher('social_graph', $$
MERGE (:Segment {
  segment_key:'seg_001',
  name:'New Users',
  segment_type:'lifecycle',
  description:'First-time customers',
  definition:'Profiles created within last 7 days',
  is_dynamic:true,
  totalCount:100,
  marketing_goals:'Onboarding'
})

MERGE (:Segment {
  segment_key:'seg_002',
  name:'VIP Customers',
  segment_type:'value',
  description:'High-value customers',
  definition:'Total investment amount > 10,000',
  is_dynamic:true,
  totalCount:50,
  marketing_goals:'Retention'
})

MERGE (:Segment {
  segment_key:'seg_003',
  name:'Engaged Users',
  segment_type:'behavioral',
  description:'Active users in last 30 days',
  definition:'Has recent interactions or investments',
  is_dynamic:true,
  totalCount:200,
  marketing_goals:'Engagement'
})
$$) AS (v agtype);


-- ---------------------------------------------------------
-- Insert Relationships
-- ---------------------------------------------------------

-- Investments

-- Alice: long-term, medium risk → growth-oriented strategy
-- NVDA
SELECT * FROM cypher('social_graph', $$
MATCH (a:Profile {profile_key:'u_001'})
MATCH (s:Profile {profile_key:'s_001'}) 

MERGE (a)-[:INVESTS {
  amount:15000,
  horizon:'long',
  risk:'medium',
  strategy:'capital_growth',
  rationale:'belief in long-term AI demand'
}]->(s)

RETURN count(*)
$$) AS (c agtype);

-- Bob: short-term, high risk → speculative trading
-- BTC
SELECT * FROM cypher('social_graph', $$
MATCH (b:Profile {profile_key:'u_002'})
MATCH (s:Profile {profile_key:'s_003'}) 

MERGE (b)-[:INVESTS {
  amount:5000,
  horizon:'short',
  risk:'high',
  strategy:'speculative_trading',
  rationale:'short-term price volatility'
}]->(s)

RETURN count(*)
$$) AS (c agtype);

-- Diana: long-term, low risk → capital preservation
-- VNM ETF
SELECT * FROM cypher('social_graph', $$
MATCH (d:Profile {profile_key:'u_004'})
MATCH (s:Profile {profile_key:'s_005'}) 

MERGE (d)-[:INVESTS {
  amount:20000,
  horizon:'long',
  risk:'low',
  strategy:'capital_preservation',
  rationale:'stable returns and diversification'
}]->(s)

RETURN count(*)
$$) AS (c agtype);

-- Employment
SELECT * FROM cypher('social_graph', $$
MATCH (a:Profile {profile_key:'u_001'}), (c:Profile {profile_key:'c_001'})
MERGE (a)-[:WORKS_FOR {role:'AI Lead'}]->(c)
RETURN count(*)
$$) AS (c agtype);

SELECT * FROM cypher('social_graph', $$
MATCH (e:Profile {profile_key:'u_005'}), (c:Profile {profile_key:'c_003'})
MERGE (e)-[:WORKS_FOR {role:'Risk Analyst'}]->(c)
RETURN count(*)
$$) AS (c agtype);

-- Social links
SELECT * FROM cypher('social_graph', $$
MATCH (c:Profile {profile_key:'u_003'}), (a:Profile {profile_key:'u_001'})
MERGE (c)-[:FOLLOWS]->(a)
RETURN count(*)
$$) AS (c agtype);

SELECT * FROM cypher('social_graph', $$
MATCH (d:Profile {profile_key:'u_004'}), (b:Profile {profile_key:'u_002'})
MERGE (d)-[:FOLLOWS]->(b)
RETURN count(*)
$$) AS (c agtype);

-- Preferences
SELECT * FROM cypher('social_graph', $$
MATCH (a:Profile {profile_key:'u_001'}), (b:Profile {profile_key:'b_002'})
MERGE (a)-[:LIKES {reason:'financial thinking'}]->(b)
RETURN count(*)
$$) AS (c agtype);

-- ---------------------------------------------------------
-- In CDP Segment : A profile can belong to multiple segments.
-- Improved BELONG_TO relationship with reasoning metadata
-- ---------------------------------------------------------
SELECT * FROM cypher('social_graph', $$
MATCH (p:Profile {profile_key:'u_001'})
MATCH (s1:Segment {segment_key:'seg_001'})
MATCH (s2:Segment {segment_key:'seg_003'})

MERGE (p)-[:BELONG_TO {
  since:'2026-01-01',
  source:'rule_engine',
  confidence:0.95,
  snapshot_date:'2026-01-14'
}]->(s1)

MERGE (p)-[:BELONG_TO {
  since:'2025-12-15',
  source:'behavioral_model',
  confidence:0.87,
  snapshot_date:'2026-01-14'
}]->(s2)

RETURN count(*)
$$) AS (c agtype);


-- ---------------------------------------------------------
-- Indexes for AGE graph tables (PostgreSQL level)
-- Notes:
--   • AGE stores node/edge properties as agtype JSON
--   • B-tree + agtype_access_operator is the safest choice
--   • These indexes are critical once data > 100k rows
-- ---------------------------------------------------------

-- 1. Node identity lookup (absolute must-have)
-- Used by almost every MATCH with {profile_key: ...}
CREATE INDEX IF NOT EXISTS idx_profile_profile_key
ON social_graph."Profile"
USING btree (
  agtype_access_operator(properties, '"profile_key"'::agtype)
);

-- 2. Node type filtering (person / company / stock / place)
-- Speeds up segmentation and persona queries
CREATE INDEX IF NOT EXISTS idx_profile_profile_type
ON social_graph."Profile"
USING btree (
  agtype_access_operator(properties, '"profile_type"'::agtype)
);

-- 3. Optional but high-value: geographic segmentation
-- Useful for CDP, marketing, localization use cases
CREATE INDEX IF NOT EXISTS idx_profile_city
ON social_graph."Profile"
USING btree (
  agtype_access_operator(properties, '"city"'::agtype)
);

-- 4. Company / asset classification
-- Enables industry ↔ sector mismatch analysis
CREATE INDEX IF NOT EXISTS idx_profile_industry
ON social_graph."Profile"
USING btree (
  agtype_access_operator(properties, '"industry"'::agtype)
);

CREATE INDEX IF NOT EXISTS idx_profile_sector
ON social_graph."Profile"
USING btree (
  agtype_access_operator(properties, '"sector"'::agtype)
);

-- ---------------------------------------------------------
-- Relationship indexes
-- ---------------------------------------------------------

-- 5. INVESTS.amount
-- Enables range queries, ranking, thresholds
CREATE INDEX IF NOT EXISTS idx_invests_amount
ON social_graph."INVESTS"
USING btree (
  agtype_access_operator(properties, '"amount"'::agtype)
);

-- 6. INVESTS.risk
-- Speeds up risk-based investor segmentation
CREATE INDEX IF NOT EXISTS idx_invests_risk
ON social_graph."INVESTS"
USING btree (
  agtype_access_operator(properties, '"risk"'::agtype)
);

-- 7. INVESTS.horizon
-- Useful for short vs long-term strategy grouping
CREATE INDEX IF NOT EXISTS idx_invests_horizon
ON social_graph."INVESTS"
USING btree (
  agtype_access_operator(properties, '"horizon"'::agtype)
);

-- ---------------------------------------------------------
-- 8. INVESTS.strategy : Strategy-based investor segmentation
-- ---------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_invests_strategy
ON social_graph."INVESTS"
USING btree (
  agtype_access_operator(properties, '"strategy"'::agtype)
);


-- ---------------------------------------------------------
-- Segment indexes (critical for CDP scale)
-- ---------------------------------------------------------

-- Segment key lookup
CREATE INDEX IF NOT EXISTS idx_segment_segment_key
ON social_graph."Segment"
USING btree (
  agtype_access_operator(properties, '"segment_key"'::agtype)
);

-- Segment type filtering (behavioral / lifecycle / value)
CREATE INDEX IF NOT EXISTS idx_segment_segment_type
ON social_graph."Segment"
USING btree (
  agtype_access_operator(properties, '"segment_type"'::agtype)
);

-- Dynamic vs static segments
CREATE INDEX IF NOT EXISTS idx_segment_is_dynamic
ON social_graph."Segment"
USING btree (
  agtype_access_operator(properties, '"is_dynamic"'::agtype)
);


-- ---------------------------------------------------------
-- Demo Queries (Reasoning Tests)
-- ---------------------------------------------------------

-- 1. Full relationship scan
SELECT * FROM cypher('social_graph', $$
MATCH (n)-[r]->(m)
RETURN DISTINCT n.name, type(r), m.name
$$) AS (from_node TEXT, rel TEXT, to_node TEXT);

-- 2. Social influence → investment
SELECT * FROM cypher('social_graph', $$
MATCH (f)-[:FOLLOWS]->(l)-[:INVESTS]->(s)
RETURN DISTINCT f.name, l.name, s.name
$$) AS (follower TEXT, leader TEXT, asset TEXT);

-- 3. Investor segmentation
SELECT * FROM cypher('social_graph', $$
MATCH (p)-[i:INVESTS]->(s)
RETURN DISTINCT p.name, s.name, i.risk, i.horizon
$$) AS (person TEXT, asset TEXT, risk TEXT, horizon TEXT);

-- 4. Employees investing outside their industry
SELECT * FROM cypher('social_graph', $$
MATCH (p)-[:WORKS_FOR]->(c),(p)-[:INVESTS]->(s)
WHERE c.industry <> s.sector
RETURN DISTINCT p.name, c.name, s.name
$$) AS (person TEXT, company TEXT, asset TEXT);

-- ---------------------------------------------------------
-- 5. Profiles grouped by segment with reasoning metadata
-- ---------------------------------------------------------
SELECT * FROM cypher('social_graph', $$
MATCH (p:Profile)-[b:BELONG_TO]->(s:Segment)
RETURN DISTINCT
  p.name            AS profile,
  p.profile_type    AS type,
  s.name            AS segment,
  s.segment_type    AS segment_type,
  b.source          AS source,
  b.confidence      AS confidence
ORDER BY s.name, b.confidence DESC
$$) AS (
  profile TEXT,
  type TEXT,
  segment TEXT,
  segment_type TEXT,
  source TEXT,
  confidence FLOAT
);

-- ---------------------------------------------------------
-- Make Diana a true VIP customer
-- ---------------------------------------------------------
SELECT * FROM cypher('social_graph', $$
MATCH (p:Profile {profile_key:'u_004'})
MATCH (s:Segment {segment_key:'seg_002'})  

MERGE (p)-[:BELONG_TO {
  since:'2025-10-01',
  source:'rule_engine',
  confidence:0.98,
  snapshot_date:'2026-01-14'
}]->(s)

RETURN count(*)
$$) AS (c agtype);

-- ---------------------------------------------------------
-- Add Bob as a secondary VIP (higher risk profile)
-- ---------------------------------------------------------
SELECT * FROM cypher('social_graph', $$
MATCH (p:Profile {profile_key:'u_002'})
MATCH (vip:Segment {segment_key:'seg_002'})
MATCH (asset:Profile {profile_key:'s_004'}) 

MERGE (p)-[:BELONG_TO {
  since:'2025-11-20',
  source:'ml_model',
  confidence:0.82,
  snapshot_date:'2026-01-14'
}]->(vip)

MERGE (p)-[:INVESTS {
  amount:18000,
  horizon:'long',
  risk:'medium',
  strategy:'growth'
}]->(asset)

RETURN count(*)
$$) AS (c agtype);

-- ---------------------------------------------------------
-- Add a VIP-grade investment for Diana
-- ---------------------------------------------------------
SELECT * FROM cypher('social_graph', $$
MATCH (p:Profile {profile_key:'u_004'})
MATCH (s:Profile {profile_key:'s_005'})  

MERGE (p)-[:INVESTS {
  amount:30000,
  horizon:'long',
  risk:'low',
  strategy:'capital_preservation'
}]->(s)

RETURN count(*)
$$) AS (c agtype);

-- ---------------------------------------------------------
-- 6. Targetable high-value segment reasoning query
-- E.g: “Give me VIP users who are long-term, low-risk investors”
-- ---------------------------------------------------------

SELECT * FROM cypher('social_graph', $$
MATCH (p:Profile)-[:BELONG_TO]->(s:Segment {segment_key:'seg_002'})
MATCH (p)-[i:INVESTS]->(a:Profile)
WHERE i.horizon = 'long' AND i.risk = 'low'
RETURN DISTINCT
  p.name AS customer,
  a.name AS asset,
  i.amount AS amount,
  i.horizon AS horizon,
  i.strategy AS strategy,
  i.risk AS risk
$$) AS (
  customer TEXT,
  asset TEXT,
  amount FLOAT,
  horizon TEXT,
  strategy TEXT,
  risk TEXT
);
