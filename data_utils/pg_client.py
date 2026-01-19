from data_utils.settings import DatabaseSettings
import psycopg
from psycopg.rows import dict_row




def get_pg_connection(settings: DatabaseSettings) -> psycopg.Connection:
    """
    Create a PostgreSQL connection using Settings.
    """
    return psycopg.connect(
        settings.pg_dsn,
        row_factory=dict_row,
    )
