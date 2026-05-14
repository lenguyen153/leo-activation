from urllib.parse import quote_plus
import psycopg
from pydantic import Field
from pydantic_settings import BaseSettings
from psycopg.rows import dict_row
from arango import ArangoClient


class DatabaseSettings(BaseSettings):
    """
    Database connection settings for PostgreSQL and ArangoDB.
    """
    
    # -------------------------
    # PostgreSQL (Target — default / UAT)
    # -------------------------
    PGSQL_DB_HOST: str = Field(default="localhost")
    PGSQL_DB_PORT: int = Field(default=5435)
    PGSQL_DB_NAME: str = Field(default="leo_cdp")
    PGSQL_DB_USER: str = Field(default="postgres")
    PGSQL_DB_PASSWORD: str

    # -------------------------
    # PostgreSQL (Production — read-only views)
    # Only the host differs; all other credentials are shared.
    # -------------------------
    PGSQL_DB_HOST_PROD: str = Field(default="")

    # -------------------------
    # API DB environment switch
    # Set API_DB_ENV=local in .env to hit the local DB instead of prod.
    # -------------------------
    API_DB_ENV: str = Field(default="prod")

    # -------------------------
    # ArangoDB (Source)
    # -------------------------
    ARANGO_HOST: str = Field(default="http://192.168.109.210:8529")
    ARANGO_DB: str = Field(default="leo_cdp_source")
    ARANGO_USER: str = Field(default="root")
    ARANGO_PASSWORD: str

    class Config:
        # Pydantic automatically handles the priority:
        # 1. OS Environment Variables (Highest Priority - Docker overrides this)
        # 2. .env file values
        # 3. Default values (Lowest Priority)
        
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore" # Ignores other extra fields

    def _build_dsn(self, host: str) -> str:
        encoded_password = quote_plus(self.PGSQL_DB_PASSWORD)
        return (
            f"postgresql://{self.PGSQL_DB_USER}:{encoded_password}@"
            f"{host}:{self.PGSQL_DB_PORT}/"
            f"{self.PGSQL_DB_NAME}?options=-c%20search_path%3Dag_catalog,public"
        )

    @property
    def pg_dsn(self) -> str:
        """Constructs the default (UAT) PostgreSQL DSN."""
        return self._build_dsn(self.PGSQL_DB_HOST)

    @property
    def pg_dsn_prod(self) -> str:
        """Constructs the production PostgreSQL DSN (read-only audience views).
        Falls back to the default host if PGSQL_DB_HOST_PROD is not set."""
        host = self.PGSQL_DB_HOST_PROD or self.PGSQL_DB_HOST
        return self._build_dsn(host)

    def get_arango_db(self):
        """
        Create and return an ArangoDB database connection.
        """

        client = ArangoClient(hosts=self.ARANGO_HOST)

        db = client.db(
            self.ARANGO_DB,
            username=self.ARANGO_USER,
            password=self.ARANGO_PASSWORD,
        )

        # Optional but useful sanity check
        print(f"🔌 Connected to ArangoDB database: {db.name}")

        if db.name != self.ARANGO_DB:
            print(
                f"⚠️ WARNING: Expected '{self.ARANGO_DB}', "
                f"but connected to '{db.name}'"
            )

        return db
        
    def get_pg_connection(self) -> psycopg.Connection:
        """Returns a connection to the default (UAT) PostgreSQL instance."""
        return psycopg.connect(self.pg_dsn, row_factory=dict_row)

    def get_pg_connection_prod(self) -> psycopg.Connection:
        """Returns a connection to the production PostgreSQL instance (read-only use only)."""
        return psycopg.connect(self.pg_dsn_prod, row_factory=dict_row)

    def get_pg_connection_api(self) -> psycopg.Connection:
        """Returns local or prod connection based on API_DB_ENV (.env switch)."""
        if self.API_DB_ENV == "local":
            return self.get_pg_connection()
        return self.get_pg_connection_prod()