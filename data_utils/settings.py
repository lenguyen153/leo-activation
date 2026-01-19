
from pydantic import BaseSettings, Field


class DatabaseSettings(BaseSettings):
    # -------------------------
    # PostgreSQL (Target)
    # -------------------------
    DB_HOST: str = Field(default="localhost")
    DB_NAME: str = Field(default="leo_cdp")
    DB_USER: str = Field(default="postgres")
    DB_PASSWORD: str

    # -------------------------
    # ArangoDB (Source)
    # -------------------------
    ARANGO_HOST: str = Field(default="http://localhost:8529")
    ARANGO_DB: str = Field(default="leo_cdp_source")
    ARANGO_USER: str = Field(default="root")
    ARANGO_PASSWORD: str

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def pg_dsn(self) -> str:
        return (
            f"postgresql://{self.DB_USER}:"
            f"{self.DB_PASSWORD}@"
            f"{self.DB_HOST}/"
            f"{self.DB_NAME}"
        )
