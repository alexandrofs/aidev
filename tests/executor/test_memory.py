import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from executor.src.memory import AgentMemoryManager


@pytest.mark.asyncio
async def test_record_daily_summary():
    mock_repo = AsyncMock()
    mock_repo.save_agent_memory.return_value = {
        "id": "mem-123",
        "story_id": "2-3-pipeline",
        "memory_type": "daily_summary",
        "content": {"status": "COMPLETED"}
    }

    manager = AgentMemoryManager(repo=mock_repo)
    summary_data = {
        "title": "Pipeline de Validação",
        "actions": ["Implemented memory sync"],
        "test_results": {"passed": 5, "failed": 0},
        "notes": "All tests passed"
    }

    saved = await manager.record_daily_summary("2-3-pipeline", summary_data)

    assert saved["id"] == "mem-123"
    mock_repo.save_agent_memory.assert_called_once()
    call_args = mock_repo.save_agent_memory.call_args[1]
    assert call_args["story_id"] == "2-3-pipeline"
    assert call_args["memory_type"] == "daily_summary"
    assert call_args["content"]["title"] == "Pipeline de Validação"


def test_sync_memlog_file(tmp_path: Path):
    mock_repo = MagicMock()
    manager = AgentMemoryManager(repo=mock_repo)

    summary1 = {
        "timestamp": "2026-08-12T23:30:00Z",
        "title": "Pipeline de Validação",
        "status": "COMPLETED",
        "actions": ["Created validation.py", "Added unit tests"],
        "test_results": {"passed": 12, "failed": 0},
        "notes": "Sandbox validation successful"
    }

    memlog_file = manager.sync_memlog_file(tmp_path, "2-3-pipeline", summary1)
    assert memlog_file.exists()
    assert memlog_file.name == ".memlog.md"

    content = memlog_file.read_text(encoding="utf-8")
    assert "## [2026-08-12T23:30:00Z] - Story 2-3-pipeline: Pipeline de Validação" in content
    assert "- **Status:** COMPLETED" in content
    assert "- **Ações Realizadas:** Created validation.py; Added unit tests" in content
    assert "- **Resultado dos Testes:** 12 passed, 0 failed" in content
    assert "- **Aprendizados/Decisões:** Sandbox validation successful" in content

    # Test append functionality with a second entry
    summary2 = {
        "timestamp": "2026-08-12T23:45:00Z",
        "title": "Worker Integration",
        "status": "COMPLETED",
        "actions": ["Updated ExecutorWorker"],
        "test_results": {"passed": 15, "failed": 0},
        "notes": "Worker integration tested"
    }

    manager.sync_memlog_file(tmp_path, "2-3-pipeline", summary2)
    updated_content = memlog_file.read_text(encoding="utf-8")

    # Check both entries exist in sequence
    assert "Story 2-3-pipeline: Pipeline de Validação" in updated_content
    assert "Story 2-3-pipeline: Worker Integration" in updated_content
