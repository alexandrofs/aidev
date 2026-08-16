import os
import socket
import pytest

os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"

from sqlalchemy import create_engine, inspect, text
from alembic.config import Config
from alembic import command


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



@pytest.fixture(scope="module")
def migrated_db(postgres_url):
    """Applies alembic migrations to the test PostgreSQL instance."""
    ini_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../persistence/alembic.ini"))
    alembic_cfg = Config(ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)
    
    # Run upgrade head
    command.upgrade(alembic_cfg, "head")
    
    engine = create_engine(postgres_url)
    yield engine
    
    # Clean up test records and ensure database remains in head state for dev runtime
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM audit_logs WHERE event_id LIKE 'evt_test%';"))
            conn.execute(text("DELETE FROM agent_memory WHERE story_id LIKE 'story_%';"))
            conn.execute(text("DELETE FROM events WHERE event_id LIKE 'evt_%';"))
            conn.commit()
    except Exception:
        pass
    
    command.upgrade(alembic_cfg, "head")
    engine.dispose()


def test_migration_creates_all_tables(migrated_db):
    inspector = inspect(migrated_db)
    tables = inspector.get_table_names()
    assert "events" in tables
    assert "agent_memory" in tables
    assert "audit_logs" in tables


def test_events_table_schema_and_defaults(migrated_db):
    inspector = inspect(migrated_db)
    columns = {col["name"]: col for col in inspector.get_columns("events")}
    
    expected_cols = ["id", "event_id", "event_type", "status", "payload", "repository", "retry_count", "error_log", "created_at", "updated_at"]
    for col_name in expected_cols:
        assert col_name in columns, f"Column {col_name} missing from events table"
        
    with migrated_db.connect() as conn:
        res = conn.execute(
            text("""
                INSERT INTO events (event_id, event_type, payload, repository)
                VALUES ('evt_test_1', 'push', '{"ref": "refs/heads/main"}'::jsonb, 'owner/repo')
                RETURNING id, status, repository, retry_count, error_log, created_at, updated_at;
            """)
        )
        row = res.fetchone()
        conn.commit()
        assert row is not None
        assert row.status == "PENDING"
        assert row.repository == "owner/repo"
        assert row.retry_count == 0
        assert row.error_log is None
        assert row.created_at is not None
        assert row.updated_at is not None


def test_migration_004_error_log_upgrade_downgrade(postgres_url):
    ini_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../persistence/alembic.ini"))
    alembic_cfg = Config(ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)

    engine = create_engine(postgres_url)
    try:
        # Downgrade para 003
        command.downgrade(alembic_cfg, "003_agent_memory_event_id")
        inspector = inspect(engine)
        cols_003 = [col["name"] for col in inspector.get_columns("events")]
        assert "error_log" not in cols_003

        # Upgrade de volta para head (005)
        command.upgrade(alembic_cfg, "head")
        inspector = inspect(engine)
        cols_head = [col["name"] for col in inspector.get_columns("events")]
        assert "error_log" in cols_head
        assert "repository" in cols_head
    finally:
        command.upgrade(alembic_cfg, "head")
        engine.dispose()


def test_migration_005_repository_upgrade_downgrade(postgres_url):
    ini_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../persistence/alembic.ini"))
    alembic_cfg = Config(ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)

    engine = create_engine(postgres_url)
    try:
        # Downgrade para 004
        command.downgrade(alembic_cfg, "004_add_error_log_to_events")
        inspector = inspect(engine)
        cols_004 = [col["name"] for col in inspector.get_columns("events")]
        assert "repository" not in cols_004
        indexes_004 = [idx["name"] for idx in inspector.get_indexes("events")]
        assert "idx_events_repository" not in indexes_004
        assert "idx_events_repository_status" not in indexes_004

        # Upgrade de volta para head (005)
        command.upgrade(alembic_cfg, "head")
        inspector = inspect(engine)
        cols_005 = [col["name"] for col in inspector.get_columns("events")]
        assert "repository" in cols_005
        indexes_005 = [idx["name"] for idx in inspector.get_indexes("events")]
        assert "idx_events_repository" in indexes_005
        assert "idx_events_repository_status" in indexes_005
    finally:
        command.upgrade(alembic_cfg, "head")
        engine.dispose()


def test_events_unique_constraint(migrated_db):
    with migrated_db.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO events (event_id, event_type, payload)
                VALUES ('evt_unique_1', 'push', '{}'::jsonb);
            """)
        )
        conn.commit()

        with pytest.raises(Exception) as excinfo:
            conn.execute(
                text("""
                    INSERT INTO events (event_id, event_type, payload)
                    VALUES ('evt_unique_1', 'push', '{}'::jsonb);
                """)
            )
            conn.commit()
        assert "evt_unique_1" in str(excinfo.value) or "unique" in str(excinfo.value).lower()


def test_events_indexes_exist(migrated_db):
    inspector = inspect(migrated_db)
    indexes = inspector.get_indexes("events")
    index_names = {idx["name"]: idx for idx in indexes}
    
    assert "idx_events_status_type" in index_names
    assert index_names["idx_events_status_type"]["column_names"] == ["status", "event_type"]
    
    assert "idx_events_status_type_created" in index_names
    assert index_names["idx_events_status_type_created"]["column_names"] == ["status", "event_type", "created_at"]
    
    assert "idx_events_event_id" in index_names
    assert index_names["idx_events_event_id"]["column_names"] == ["event_id"]

    assert "idx_events_repository" in index_names
    assert index_names["idx_events_repository"]["column_names"] == ["repository"]

    assert "idx_events_repository_status" in index_names
    assert index_names["idx_events_repository_status"]["column_names"] == ["repository", "status"]


def test_agent_memory_schema_and_indexes(migrated_db):
    inspector = inspect(migrated_db)
    columns = {col["name"]: col for col in inspector.get_columns("agent_memory")}
    
    expected_cols = ["id", "story_id", "memory_type", "content", "created_at", "updated_at"]
    for col_name in expected_cols:
        assert col_name in columns, f"Column {col_name} missing from agent_memory table"
        
    indexes = inspector.get_indexes("agent_memory")
    index_names = {idx["name"]: idx for idx in indexes}
    assert "idx_agent_memory_story_type" in index_names
    assert index_names["idx_agent_memory_story_type"]["column_names"] == ["story_id", "memory_type"]


def test_audit_logs_schema_and_indexes(migrated_db):
    inspector = inspect(migrated_db)
    columns = {col["name"]: col for col in inspector.get_columns("audit_logs")}
    
    expected_cols = ["id", "event_id", "action", "actor", "details", "created_at"]
    for col_name in expected_cols:
        assert col_name in columns, f"Column {col_name} missing from audit_logs table"
        
    indexes = inspector.get_indexes("audit_logs")
    index_names = {idx["name"]: idx for idx in indexes}
    assert "idx_audit_logs_event_id" in index_names
    assert index_names["idx_audit_logs_event_id"]["column_names"] == ["event_id"]
