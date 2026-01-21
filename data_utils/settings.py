from urllib.parse import quote_plus
from pydantic import Field
from pydantic_settings import BaseSettings

class DatabaseSettings(BaseSettings):
    # -------------------------
    # PostgreSQL (Target)
    # -------------------------
    PGSQL_DB_HOST: str = Field(default="localhost")
    PGSQL_DB_PORT: int = Field(default=5432)
    PGSQL_DB_NAME: str = Field(default="leo_cdp")
    PGSQL_DB_USER: str = Field(default="postgres")
    PGSQL_DB_PASSWORD: str

    # -------------------------
    # ArangoDB (Source)
    # -------------------------
    ARANGO_HOST: str = Field(default="http://localhost:8529")
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

    @property
    def pg_dsn(self) -> str:
        """
        Constructs a safe PostgreSQL connection string (DSN).
        Handles special characters in the password and includes the port.
        
        Updates:
        - Appends '?options=-c search_path=ag_catalog,public' 
          to ensure Apache AGE functions are loaded and prioritized.
        """
        # Safely encode the password to handle characters like '@', '/', ':'
        encoded_password = quote_plus(self.PGSQL_DB_PASSWORD)
        
        # We pass 'options' to set the search_path at connection time.
        # This is strictly required for AGE to recognize graph syntax in SQL.
        return (
            f"postgresql://{self.PGSQL_DB_USER}:{encoded_password}@"
            f"{self.PGSQL_DB_HOST}:{self.PGSQL_DB_PORT}/"
            f"{self.PGSQL_DB_NAME}?options=-c%20search_path%3Dag_catalog,public"
        )