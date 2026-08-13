import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from persistence.src.repository import EventRepository

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def async_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_memory (
                id TEXT PRIMARY KEY,
                story_id TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(async_engine) -> AsyncSession:
    async_session_factory = async_sessionmaker(bind=async_engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_factory() as session:
        yield session


@pytest.mark.asyncio
async def test_save_and_get_agent_memory(session: AsyncSession):
    repo = EventRepository(session)
    story_id = "2-3-pipeline-de-validacao-local"
    content = {
        "actions": ["Refactored repository.py", "Added unit tests"],
        "test_results": {"passed": 10, "failed": 0},
        "notes": "Validation pipeline setup completed"
    }

    # Save agent memory
    saved = await repo.save_agent_memory(
        story_id=story_id,
        memory_type="daily_summary",
        content=content
    )
    assert saved["id"] is not None
    assert saved["story_id"] == story_id
    assert saved["memory_type"] == "daily_summary"
    assert saved["content"] == content

    # Get agent memory by story_id and memory_type
    memories = await repo.get_agent_memory(story_id=story_id, memory_type="daily_summary")
    assert len(memories) == 1
    assert memories[0]["story_id"] == story_id
    assert memories[0]["memory_type"] == "daily_summary"
    assert memories[0]["content"]["test_results"]["passed"] == 10

    # Get agent memory without memory_type filter
    all_memories = await repo.get_agent_memory(story_id=story_id)
    assert len(all_memories) == 1
