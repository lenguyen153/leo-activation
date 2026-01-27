import os
import sys
from sqlalchemy import text
from sqlalchemy.orm import Session

# Boilerplate to load your settings (adjust paths as needed)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from data_utils.db_factory import get_db_context
from data_utils.settings import DatabaseSettings

class GraphDataManager:
    def __init__(self, session: Session, graph_name: str = 'investing_knowledge_graph'):
        self.session = session
        self.graph_name = graph_name
        self.cursor = session.connection().connection.cursor()

    def init_graph(self):
        """Loads Apache AGE extension and ensures the graph exists."""
        print(f"--- Initializing Graph: {self.graph_name} ---")
        
        # 1. Load AGE Extension
        self.session.execute(text("LOAD 'age';"))
        self.session.execute(text('SET search_path = ag_catalog, "$user", public;'))
        
        # 2. Create Graph (Handle existence check via try/except)
        try:
            self.session.execute(text(f"SELECT create_graph('{self.graph_name}');"))
            print("Graph created.")
        except Exception:
            print("Graph likely exists, proceeding...")
            self.session.rollback()
            # Re-apply config after rollback
            self.session.execute(text("LOAD 'age';"))
            self.session.execute(text('SET search_path = ag_catalog, "$user", public;'))

    def execute_cypher(self, cypher_query: str):
        """Helper to execute raw Cypher queries using the cursor."""
        # Wrap the specific Cypher query in the postgres function call
        full_query = f"SELECT * FROM cypher('{self.graph_name}', $$ {cypher_query} $$) as (a agtype);"
        self.cursor.execute(full_query)
        return self.cursor.fetchall()

    def execute_cypher_with_return(self, cypher_query: str, return_columns_def: str):
        """
        Helper for SELECT queries where we need specific return columns.
        :param return_columns_def: e.g. "symbol agtype, quantity agtype"
        """
        full_query = f"SELECT * FROM cypher('{self.graph_name}', $$ {cypher_query} $$) as ({return_columns_def});"
        self.cursor.execute(full_query)
        return self.cursor.fetchall()

    def seed_test_data(self):
        """Merges Nodes and Relationships for the test scenario."""
        print("\n--- Seeding Data (Nodes & Relationships) ---")
        
        query = """
            MERGE (u:User {id: 'p_alice_py', name: 'Alice Python'})
            MERGE (btc:Asset {symbol: 'BTC-USD', name: 'Bitcoin'})
            MERGE (aapl:Asset {symbol: 'AAPL', name: 'Apple'})
            MERGE (news:News {id: 'news_py_01', title: 'Python Analysis of Apple'})

            MERGE (u)-[h:HOLDS]->(btc)
            SET h.quantity = 10.5

            MERGE (u)-[f:FOLLOWS]->(aapl)
            SET f.active = true

            MERGE (u)-[r:RECOMMEND]->(news)
            SET r.score = 0.95, r.algorithm = 'content_similarity'
            
            MERGE (news)-[:ABOUT]->(aapl)
        """
        # Execute (results ignored for merge)
        self.execute_cypher(query)
        print("Seed complete.")

    def get_user_holdings(self, user_id: str):
        """Fetches assets held by a user."""
        print(f"\n--- Holdings for {user_id} ---")
        
        query = f"""
            MATCH (u:User {{id: '{user_id}'}})-[r:HOLDS]->(a:Asset)
            RETURN a.symbol, r.quantity
        """
        rows = self.execute_cypher_with_return(query, "symbol agtype, quantity agtype")
        
        for r in rows:
            print(f" - Symbol: {r[0]}, Qty: {r[1]}")
        return rows

    def get_recommendations(self, user_id: str, min_score: float):
        """Fetches high-scoring news recommendations."""
        print(f"\n--- Recommendations (Score > {min_score}) for {user_id} ---")
        
        query = f"""
            MATCH (u:User {{id: '{user_id}'}})-[r:RECOMMEND]->(n:News)
            WHERE r.score > {min_score}
            RETURN n.title, r.score
        """
        rows = self.execute_cypher_with_return(query, "title agtype, score agtype")
        
        for r in rows:
            print(f" - News: {r[0]}, Score: {r[1]}")
        return rows

    def get_recommendation_context(self, user_id: str):
        """Traces why a news item was recommended (e.g., it is ABOUT a stock)."""
        print(f"\n--- Recommendation Context for {user_id} ---")
        
        query = f"""
            MATCH (u:User {{id: '{user_id}'}})-[r:RECOMMEND]->(n:News)-[:ABOUT]->(a:Asset)
            RETURN n.title, a.symbol
        """
        rows = self.execute_cypher_with_return(query, "news_title agtype, related_asset agtype")
        
        for r in rows:
            print(f" - The news '{r[0]}' is about '{r[1]}'")
        return rows


def run_graph_test():
    settings = DatabaseSettings()
    
    # Use context manager for session handling
    with get_db_context(settings) as session:
        # Instantiate our Graph Manager
        graph_manager = GraphDataManager(session)
        
        # 1. Initialize
        graph_manager.init_graph()
        
        # 2. Seed Data
        graph_manager.seed_test_data()
        
        # 3. Run Queries
        user_id = 'p_alice_py'
        graph_manager.get_user_holdings(user_id)
        graph_manager.get_recommendations(user_id, min_score=0.9)
        graph_manager.get_recommendation_context(user_id)

if __name__ == "__main__":
    try:
        run_graph_test()
        print("\nTest Finished Successfully.")
    except Exception as e:
        print(f"Test Failed: {e}")