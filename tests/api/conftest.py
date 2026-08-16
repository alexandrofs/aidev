import sys
import hmac
import hashlib
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text

# Ensure api module is in sys.path
root_dir = Path(__file__).parent.parent.parent
api_dir = root_dir / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from src.main import app
from src.database import get_async_session
from src.config import settings

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY DEFAULT '00000000-0000-0000-0000-000000000001',
                event_id TEXT UNIQUE NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                payload TEXT NOT NULL,
                repository TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                error_log TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    async_session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def webhook_secret():
    return settings.GITHUB_WEBHOOK_SECRET


@pytest.fixture
def make_signature(webhook_secret):
    def _make(body: bytes) -> str:
        sig = hmac.new(webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return f"sha256={sig}"
    return _make
