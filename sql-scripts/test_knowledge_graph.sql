-- ============================================================
-- 1. SETUP ENVIRONMENT
-- ============================================================
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Create graph if it doesn't exist (returns false if already exists, safe to ignore error)
-- SELECT create_graph('investing_knowledge_graph');

-- ============================================================
-- 2. SEED DATA (NODES & EDGES)
-- ============================================================
SELECT * FROM cypher('investing_knowledge_graph', $$

    MERGE (u:User {id: 'p_alice', name: 'Alice'})
    MERGE (stock:Asset {symbol: 'AAPL', name: 'Apple Inc.'})
    MERGE (crypto:Asset {symbol: 'BTC-USD', name: 'Bitcoin'})
    MERGE (news:News {id: 'news_101', title: 'Apple releases new VR headset'})


    MERGE (u)-[h:HOLDS]->(crypto)
    SET h.quantity = 2.5, h.updated_at = '2024-01-26'


    MERGE (u)-[f:FOLLOWS]->(stock)
    SET f.since = '2024-01-01', f.source = 'manual_click'


    MERGE (u)-[r:RECOMMEND]->(news)
    SET r.score = 0.89, r.reason = 'User follows related asset'


    MERGE (news)-[:ABOUT]->(stock)
$$) as (a agtype);

-- ============================================================
-- 3. TEST QUERIES
-- ============================================================

-- TEST A: What does Alice HOLD?
SELECT * FROM cypher('investing_knowledge_graph', $$
    MATCH (u:User {id: 'p_alice'})-[r:HOLDS]->(a:Asset)
    RETURN u.name, type(r), a.symbol, r.quantity
$$) as (user_name agtype, relation agtype, symbol agtype, qty agtype);

-- TEST B: What does Alice FOLLOW?
SELECT * FROM cypher('investing_knowledge_graph', $$
    MATCH (u:User {id: 'p_alice'})-[r:FOLLOWS]->(a:Asset)
    RETURN u.name, type(r), a.symbol, r.since
$$) as (user_name agtype, relation agtype, symbol agtype, since agtype);

-- TEST C: What News is RECOMMENDED to Alice (Score > 0.8)?
SELECT * FROM cypher('investing_knowledge_graph', $$
    MATCH (u:User {id: 'p_alice'})-[r:RECOMMEND]->(n:News)
    WHERE r.score > 0.8
    RETURN u.name, 'RECOMMENDED', n.title, r.score
$$) as (user_name agtype, relation agtype, title agtype, score agtype);