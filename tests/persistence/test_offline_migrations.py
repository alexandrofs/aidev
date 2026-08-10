import os
from alembic.config import Config
from alembic import command

def test_alembic_offline_ddl_generation(capsys):
    ini_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../persistence/alembic.ini"))
    alembic_cfg = Config(ini_path)
    
    # Run alembic upgrade head --sql
    command.upgrade(alembic_cfg, "head", sql=True)
    
    captured = capsys.readouterr()
    output_sql = captured.out
    
    assert "CREATE TABLE events" in output_sql
    assert "CREATE TABLE agent_memory" in output_sql
    assert "CREATE TABLE audit_logs" in output_sql
    
    assert "CREATE INDEX idx_events_status_type ON events (status, event_type)" in output_sql
    assert "CREATE UNIQUE INDEX idx_events_event_id ON events (event_id)" in output_sql
    assert "CREATE INDEX idx_agent_memory_story_type ON agent_memory (story_id, memory_type)" in output_sql
    assert "CREATE INDEX idx_audit_logs_event_id ON audit_logs (event_id)" in output_sql
    assert "DEFAULT 'PENDING'" in output_sql
