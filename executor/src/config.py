import uuid
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    DOCKER_SOCKET: str = "unix:///var/run/docker.sock"
    SANDBOX_IMAGE: str = "python:3.12-slim"
    POLL_INTERVAL: float = 2.0
    MAX_POLL_INTERVAL: float = 30.0
    BACKOFF_FACTOR: float = 1.5
    WORKER_ID: str = Field(default_factory=lambda: f"executor-worker-{uuid.uuid4().hex[:8]}")
    CONTAINER_TIMEOUT: int = 300

    PROJECT_ROOT: str = Field(default_factory=lambda: str(Path(__file__).resolve().parent.parent.parent))

    MCP_CONFIG_PATH: str = "mcp_config.json"
    SKILLS_DIR: str = ".agents/skills"
    PROMPTS_DIR: str = "executor/prompts"
    MANDATORY_PROMPTS: list[str] = Field(default_factory=lambda: ["coding.md", "review.md"])
    DEFAULT_WORKFLOW_PHASES: list[str] = Field(default_factory=lambda: ["coding", "review"])
    VALIDATION_COMMANDS: list[str] = Field(default_factory=lambda: ["pytest"])
    MEMLOG_FILENAME: str = ".memlog.md"

    # Configurações de execução autônoma com OpenCode
    OPENCODE_RUN_COMMAND: str = 'opencode run "$(cat {prompt_path})" --auto'
    OPENCODE_MODEL: Optional[str] = None
    OPENCODE_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None

    # Configurações de Git / Autor
    GIT_AUTHOR_NAME: str = "AI Developer Agent"
    GIT_AUTHOR_EMAIL: str = "aidev-agent@noreply.github.com"

    # Configurações de integração com GitHub (Story 3.2)
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_REPOSITORY: Optional[str] = None
    GITHUB_API_URL: str = "https://api.github.com"
    GITHUB_BASE_BRANCH: str = "main"
    GITHUB_PROJECT_ID: Optional[str] = None
    GITHUB_DRY_RUN: bool = False

    def resolve_path(self, path_str: str) -> Path:
        p = Path(path_str)
        if p.is_absolute():
            return p
        root = Path(self.PROJECT_ROOT) if hasattr(self, "PROJECT_ROOT") and self.PROJECT_ROOT else Path(__file__).resolve().parent.parent.parent
        return root / p

    @property
    def resolved_mcp_config_path(self) -> Path:
        return self.resolve_path(self.MCP_CONFIG_PATH)

    @property
    def resolved_skills_dir(self) -> Path:
        return self.resolve_path(self.SKILLS_DIR)

    @property
    def resolved_prompts_dir(self) -> Path:
        return self.resolve_path(self.PROMPTS_DIR)

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "aidev"
    POSTGRES_USER: str = "aidev"
    POSTGRES_PASSWORD: str = "aidev"
    DATABASE_URL: Optional[str] = None

    @property
    def async_database_url(self) -> str:
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+psycopg://", 1)
            elif url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            elif url.startswith("postgresql+psycopg2://"):
                url = url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
            return url
        return f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


settings = ExecutorSettings()
