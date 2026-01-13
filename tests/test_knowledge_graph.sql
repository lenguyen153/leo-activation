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
-- Insert Relationships
-- ---------------------------------------------------------

-- Investments
SELECT * FROM cypher('social_graph', $$
MATCH (a:Profile {profile_key:'u_001'}), (s:Profile {profile_key:'s_001'})
MERGE (a)-[:INVESTS {amount:15000, horizon:'long', risk:'medium'}]->(s)
RETURN count(*)
$$) AS (c agtype);

SELECT * FROM cypher('social_graph', $$
MATCH (b:Profile {profile_key:'u_002'}), (s:Profile {profile_key:'s_003'})
MERGE (b)-[:INVESTS {amount:5000, horizon:'short', risk:'high'}]->(s)
RETURN count(*)
$$) AS (c agtype);

SELECT * FROM cypher('social_graph', $$
MATCH (d:Profile {profile_key:'u_004'}), (s:Profile {profile_key:'s_005'})
MERGE (d)-[:INVESTS {amount:20000, horizon:'long', risk:'low'}]->(s)
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
