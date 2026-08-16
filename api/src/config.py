from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    GITHUB_WEBHOOK_SECRET: str = "default_secret"
    GITHUB_TOKEN: str = ""
    GITHUB_API_URL: str = "https://api.github.com"
    DEFAULT_GITHUB_REPOSITORY: Optional[str] = None
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "aidev"
    POSTGRES_USER: str = "aidev"
    POSTGRES_PASSWORD: str = "aidev"
    DATABASE_URL: str = ""
    API_PORT: int = 8000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def get_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


settings = Settings()
