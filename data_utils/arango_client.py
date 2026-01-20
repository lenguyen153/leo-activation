from arango import ArangoClient
from data_utils.settings import DatabaseSettings

def get_arango_db(settings: DatabaseSettings):
    """
    Create and return an ArangoDB database connection.
    """

    client = ArangoClient(hosts=settings.ARANGO_HOST)

    db = client.db(
        settings.ARANGO_DB,
        username=settings.ARANGO_USER,
        password=settings.ARANGO_PASSWORD,
    )

    # Optional but useful sanity check
    print(f"🔌 Connected to ArangoDB database: {db.name}")

    if db.name != settings.ARANGO_DB:
        print(
            f"⚠️ WARNING: Expected '{settings.ARANGO_DB}', "
            f"but connected to '{db.name}'"
        )

    return db
