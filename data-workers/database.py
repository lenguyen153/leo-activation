
import os
import psycopg
from arango import ArangoClient

# --- PostgreSQL Connection ---
PG_DSN = "postgresql://{user}:{password}@{host}/{dbname}".format(
    user=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASSWORD", "password"),
    host=os.getenv("DB_HOST", "localhost"),
    dbname=os.getenv("DB_NAME", "leo_cdp")
)

def get_pg_connection():
    return psycopg.connect(PG_DSN, row_factory=psycopg.rows.dict_row)

# --- ArangoDB Connection ---
def get_arango_db():
    client = ArangoClient(hosts=os.getenv("ARANGO_HOST", "http://localhost:8529"))
    db = client.db(
        os.getenv("ARANGO_DB", "leo_cdp_source"),
        username=os.getenv("ARANGO_USER", "root"),
        password=os.getenv("ARANGO_PASSWORD", "")
    )
    return db