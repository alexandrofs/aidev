import os
import sys
import json
import uuid
import socket
import asyncio
from pathlib import Path
import pytest

root_dir = Path(__file__).parent.parent.parent
persistence_dir = root_dir / "persistence"
if str(persistence_dir) not in sys.path:
    sys.path.insert(0, str(persistence_dir))
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
import pytest_asyncio
from alembic.config import Config
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text

from persistence.src.repository import EventRepository, compute_payload_hash, EventRecord


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


def is_postgres_reachable(host="localhost", port=5432):
    try:
        from sqlalchemy import create_engine, text
        url = f"postgresql+psycopg://aidev:aidev@{host}:{port}/aidev"
        engine = create_engine(url, connect_args={"connect_timeout": 1})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False



@pytest.fixture(scope="module")
def postgres_url():
    """Provides a PostgreSQL connection URL using local PG or testcontainers."""
    local_db = os.environ.get("TEST_DATABASE_URL")
    if local_db:
        yield local_db
    elif is_postgres_reachable("localhost", 5432):
        yield "postgresql+psycopg://aidev:aidev@localhost:5432/aidev"
    else:
        try:
            from testcontainers.postgres import PostgresContainer
            with PostgresContainer("postgres:16-alpine") as postgres:
                db_url = postgres.get_connection_url().replace("postgresql+psycopg2://", "postgresql+psycopg://").replace("postgresql://", "postgresql+psycopg://")
                yield db_url
        except Exception as e:
            pytest.skip(f"PostgreSQL container unavailable: {e}")



@pytest_asyncio.fixture
async def async_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                event_id TEXT UNIQUE NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                payload TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                error_log TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                event_id TEXT,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(async_engine) -> AsyncSession:
    async_session_factory = async_sessionmaker(bind=async_engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_factory() as session:
        yield session


def test_compute_payload_hash():
    payload1 = {"b": 2, "a": 1, "nested": {"y": "val2", "x": "val1"}}
    payload2 = {"a": 1, "b": 2, "nested": {"x": "val1", "y": "val2"}}
    
    hash1 = compute_payload_hash(payload1)
    hash2 = compute_payload_hash(payload2)
    
    assert hash1 == hash2
    assert len(hash1) == 64


@pytest.mark.asyncio
async def test_claim_event_success(session: AsyncSession):
    repo = EventRepository(session)
    
    await session.execute(text("""
        INSERT INTO events (id, event_id, event_type, status, payload, retry_count)
        VALUES ('uuid-1', 'evt-100', 'push', 'PENDING', '{"ref": "refs/heads/main"}', 0)
    """))
    await session.commit()
    
    event = await repo.claim_event(event_types=["push", "issues"], worker_id="worker-1")
    assert event is not None
    assert event.event_id == "evt-100"
    assert event.status == "PROCESSING"
    
    result = await session.execute(text("SELECT * FROM audit_logs WHERE event_id = 'evt-100'"))
    log = result.fetchone()
    assert log is not None
    assert log.action == "CLAIMED"
    assert log.actor == "worker-1"


@pytest.mark.asyncio
async def test_claim_event_no_match(session: AsyncSession):
    repo = EventRepository(session)
    
    await session.execute(text("""
        INSERT INTO events (id, event_id, event_type, status, payload, retry_count)
        VALUES ('uuid-2', 'evt-101', 'pull_request', 'PENDING', '{"action": "opened"}', 0)
    """))
    await session.commit()
    
    event = await repo.claim_event(event_types=["push"], worker_id="worker-1")
    assert event is None


@pytest.mark.asyncio
async def test_complete_event(session: AsyncSession):
    repo = EventRepository(session)
    
    await session.execute(text("""
        INSERT INTO events (id, event_id, event_type, status, payload, retry_count)
        VALUES ('uuid-3', 'evt-102', 'push', 'PROCESSING', '{"ref": "main"}', 0)
    """))
    await session.commit()
    
    success = await repo.complete_event(event_id="evt-102", worker_id="worker-1", details={"result": "ok"})
    assert success is True
    
    res = await session.execute(text("SELECT status FROM events WHERE event_id = 'evt-102'"))
    row = res.fetchone()
    assert row.status == "COMPLETED"
    
    res_audit = await session.execute(text("SELECT action, actor, details FROM audit_logs WHERE event_id = 'evt-102'"))
    audit_row = res_audit.fetchone()
    assert audit_row is not None
    assert audit_row.action == "COMPLETED"
    assert audit_row.actor == "worker-1"


@pytest.mark.asyncio
async def test_fail_event_retry(session: AsyncSession):
    repo = EventRepository(session)
    
    await session.execute(text("""
        INSERT INTO events (id, event_id, event_type, status, payload, retry_count)
        VALUES ('uuid-4', 'evt-103', 'push', 'PROCESSING', '{"ref": "main"}', 0)
    """))
    await session.commit()
    
    await repo.fail_event(event_id="evt-103", worker_id="worker-1", error_message="Connection timeout", max_retries=3)
    
    res = await session.execute(text("SELECT status, retry_count, error_log FROM events WHERE event_id = 'evt-103'"))
    row = res.fetchone()
    assert row.status == "PENDING"
    assert row.retry_count == 1
    assert row.error_log == "Connection timeout"
    
    res_audit = await session.execute(text("SELECT action, details FROM audit_logs WHERE event_id = 'evt-103'"))
    audit_row = res_audit.fetchone()
    assert audit_row is not None
    assert audit_row.action == "RETRY"


@pytest.mark.asyncio
async def test_fail_event_max_retries(session: AsyncSession):
    repo = EventRepository(session)
    
    await session.execute(text("""
        INSERT INTO events (id, event_id, event_type, status, payload, retry_count)
        VALUES ('uuid-5', 'evt-104', 'push', 'PROCESSING', '{"ref": "main"}', 2)
    """))
    await session.commit()
    
    await repo.fail_event(event_id="evt-104", worker_id="worker-1", error_message="Fatal error", max_retries=3)
    
    res = await session.execute(text("SELECT status, retry_count, error_log FROM events WHERE event_id = 'evt-104'"))
    row = res.fetchone()
    assert row.status == "FAILED"
    assert row.retry_count == 3
    assert row.error_log == "Fatal error"
    
    res_audit = await session.execute(text("SELECT action, details FROM audit_logs WHERE event_id = 'evt-104'"))
    audit_row = res_audit.fetchone()
    assert audit_row is not None
    assert audit_row.action == "FAILED"


@pytest.mark.asyncio
async def test_claim_event_ignores_ignored_status(session: AsyncSession):
    repo = EventRepository(session)
    
    await session.execute(text("""
        INSERT INTO events (id, event_id, event_type, status, payload, retry_count)
        VALUES ('uuid-ignored-1', 'evt-ignored-1', 'projects_v2_item', 'IGNORED', '{"action": "edited"}', 0)
    """))
    await session.commit()
    
    claimed = await repo.claim_event(event_types=["projects_v2_item"], worker_id="worker-1")
    assert claimed is None


@pytest.mark.asyncio
async def test_check_idempotency(session: AsyncSession):
    repo = EventRepository(session)
    payload = {"issue": 123}
    payload_hash = compute_payload_hash(payload)
    
    await session.execute(text("""
        INSERT INTO events (id, event_id, event_type, status, payload, retry_count)
        VALUES ('uuid-6', 'evt-105', 'issues', 'COMPLETED', :payload, 0)
    """), {"payload": json.dumps(payload)})
    await session.commit()
    
    is_processed_id = await repo.check_idempotency(event_id="evt-105")
    assert is_processed_id is True
    
    is_processed_fake = await repo.check_idempotency(event_id="evt-999")
    assert is_processed_fake is False
    
    is_processed_hash = await repo.check_idempotency(payload_hash=payload_hash)
    assert is_processed_hash is True


@pytest.mark.asyncio
async def test_concurrent_claim_events_sqlite(async_engine):
    async_session_factory = async_sessionmaker(bind=async_engine, expire_on_commit=False, class_=AsyncSession)
    
    # Insert 5 events
    async with async_session_factory() as setup_session:
        for i in range(5):
            await setup_session.execute(text(f"""
                INSERT INTO events (id, event_id, event_type, status, payload, retry_count)
                VALUES ('uuid-conc-{i}', 'evt-conc-{i}', 'push', 'PENDING', '{{"idx": {i}}}', 0)
            """))
        await setup_session.commit()

    async def worker(worker_name: str):
        claimed = []
        async with async_session_factory() as session:
            repo = EventRepository(session)
            while True:
                evt = await repo.claim_event(event_types=["push"], worker_id=worker_name)
                if not evt:
                    break
                claimed.append(evt.event_id)
        return claimed

    # Run 5 concurrent workers
    tasks = [worker(f"worker-{i}") for i in range(5)]
    results = await asyncio.gather(*tasks)
    
    all_claimed = [evt_id for sublist in results for evt_id in sublist]
    assert len(all_claimed) == 5
    assert len(set(all_claimed)) == 5  # No duplicates claimed!


@pytest.mark.asyncio
async def test_concurrent_claim_events_postgres(postgres_url):
    ini_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../persistence/alembic.ini"))
    alembic_cfg = Config(ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(alembic_cfg, "head")

    pg_engine = create_async_engine(postgres_url, echo=False)
    async_session_factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False, class_=AsyncSession)

    prefix = f"pg-{uuid.uuid4().hex[:6]}"
    async with async_session_factory() as setup_session:
        for i in range(5):
            await setup_session.execute(text(f"""
                INSERT INTO events (id, event_id, event_type, status, payload, retry_count)
                VALUES (gen_random_uuid(), '{prefix}-evt-{i}', 'push', 'PENDING', '{{"idx": {i}}}', 0)
            """))
        await setup_session.commit()

    async def worker(worker_name: str):
        claimed = []
        async with async_session_factory() as session:
            repo = EventRepository(session)
            while True:
                evt = await repo.claim_event(event_types=["push"], worker_id=worker_name)
                if not evt:
                    break
                claimed.append(evt.event_id)
                # Filter out events not belonging to this test batch
                if not evt.event_id.startswith(prefix):
                    continue
        return claimed

    tasks = [worker(f"pg-worker-{i}") for i in range(5)]
    results = await asyncio.gather(*tasks)

    pg_claimed = [evt_id for sublist in results for evt_id in sublist if evt_id.startswith(prefix)]
    assert len(pg_claimed) == 5
    assert len(set(pg_claimed)) == 5

    await pg_engine.dispose()
