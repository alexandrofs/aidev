"""
[P2] Unit tests for Settings.get_database_url (api/src/config.py)

Verifies that the URL construction logic works correctly
with and without an explicit DATABASE_URL override.
"""
import sys
from pathlib import Path

# Ensure api/src is resolvable
root_dir = Path(__file__).parent.parent.parent
api_dir = root_dir / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from src.config import Settings  # noqa: E402


def test_get_database_url_uses_explicit_database_url():
    """[P2] When DATABASE_URL is provided, it must be returned as-is."""
    s = Settings(
        DATABASE_URL="postgresql+psycopg://custom:pass@db:5432/mydb",
        GITHUB_WEBHOOK_SECRET="secret",
    )
    assert s.get_database_url() == "postgresql+psycopg://custom:pass@db:5432/mydb"


def test_get_database_url_constructs_from_components_when_empty():
    """[P2] When DATABASE_URL is empty, URL must be assembled from component settings."""
    s = Settings(
        DATABASE_URL="",
        POSTGRES_USER="aidev",
        POSTGRES_PASSWORD="aidev",
        POSTGRES_HOST="localhost",
        POSTGRES_PORT=5432,
        POSTGRES_DB="aidev",
        GITHUB_WEBHOOK_SECRET="secret",
    )
    url = s.get_database_url()
    assert url == "postgresql+psycopg://aidev:aidev@localhost:5432/aidev"


def test_get_database_url_reflects_custom_port():
    """[P2] Custom POSTGRES_PORT must appear in the constructed URL."""
    s = Settings(
        DATABASE_URL="",
        POSTGRES_USER="user",
        POSTGRES_PASSWORD="pass",
        POSTGRES_HOST="db-host",
        POSTGRES_PORT=5433,
        POSTGRES_DB="testdb",
        GITHUB_WEBHOOK_SECRET="secret",
    )
    url = s.get_database_url()
    assert "5433" in url
    assert "db-host" in url
    assert "testdb" in url
