import pytest
import pytest_asyncio
import threading
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


@pytest.mark.asyncio
async def test_record_daily_summary_passes_event_id():
    """F5: event_id é repassado ao repositório para ativar o UPSERT de idempotência."""
    mock_repo = AsyncMock()
    mock_repo.save_agent_memory.return_value = {
        "id": "mem-456", "story_id": "s1", "memory_type": "daily_summary", "content": {}
    }

    manager = AgentMemoryManager(repo=mock_repo)
    await manager.record_daily_summary("s1", {"status": "COMPLETED"}, event_id="evt-idempotente-001")

    call_kwargs = mock_repo.save_agent_memory.call_args[1]
    assert call_kwargs["event_id"] == "evt-idempotente-001", \
        "event_id deve ser passado ao repositório para idempotência"


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


def test_sync_memlog_file_idempotent_on_retry(tmp_path: Path):
    """F5: chamar sync_memlog_file duas vezes com o mesmo timestamp não deve duplicar a entrada."""
    mock_repo = MagicMock()
    manager = AgentMemoryManager(repo=mock_repo)

    summary = {
        "timestamp": "2026-08-12T23:30:00Z",
        "title": "Retry Test",
        "status": "COMPLETED",
        "actions": ["action"],
        "test_results": {"passed": 5, "failed": 0},
        "notes": "First attempt"
    }

    manager.sync_memlog_file(tmp_path, "retry-story", summary)
    # Simula retry: mesma chamada com mesmo timestamp
    manager.sync_memlog_file(tmp_path, "retry-story", summary)

    content = (tmp_path / ".memlog.md").read_text(encoding="utf-8")
    # O cabeçalho deve aparecer exatamente uma vez
    occurrences = content.count("## [2026-08-12T23:30:00Z] - Story retry-story: Retry Test")
    assert occurrences == 1, f"Entrada duplicada detectada! Ocorrências: {occurrences}"


def test_sync_memlog_file_concurrent_writes_no_corruption(tmp_path: Path):
    """F6: múltiplas threads escrevendo no mesmo .memlog.md não devem corromper o arquivo."""
    mock_repo = MagicMock()
    manager = AgentMemoryManager(repo=mock_repo)
    errors = []

    def write_entry(thread_index: int):
        try:
            summary = {
                "timestamp": f"2026-08-12T23:{thread_index:02d}:00Z",
                "title": f"Thread {thread_index}",
                "status": "COMPLETED",
                "actions": [f"acao-{thread_index}"],
                "test_results": {"passed": thread_index, "failed": 0},
                "notes": f"nota-{thread_index}"
            }
            manager.sync_memlog_file(tmp_path, f"story-{thread_index}", summary)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=write_entry, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Erros durante escritas concorrentes: {errors}"

    content = (tmp_path / ".memlog.md").read_text(encoding="utf-8")
    # Todas as 10 entradas devem estar presentes e completas
    for i in range(10):
        assert f"story-{i}" in content, f"Entrada da thread {i} ausente no arquivo"
    # O arquivo deve ser um Markdown válido: cada entrada tem o marcador ## exatamente uma vez
    for i in range(10):
        assert content.count(f"## [2026-08-12T23:{i:02d}:00Z]") == 1, \
            f"Entrada {i} duplicada ou corrompida"


def _worker_process_write(path_str: str, proc_id: int):
    mock_repo = MagicMock()
    manager = AgentMemoryManager(repo=mock_repo)
    summary = {
        "timestamp": f"2026-08-12T23:{proc_id:02d}:00Z",
        "title": f"Process {proc_id}",
        "status": "COMPLETED",
        "actions": [f"process_action_{proc_id}"],
        "test_results": {"passed": proc_id, "failed": 0},
        "notes": f"process_note_{proc_id}"
    }
    manager.sync_memlog_file(Path(path_str), f"story-proc-{proc_id}", summary)


def test_sync_memlog_file_multiprocess_writes_with_file_lock(tmp_path: Path):
    """F6: múltiplos processos do SO concorrendo na escrita do .memlog.md via fcntl.flock."""
    import multiprocessing

    processes = []
    for i in range(8):
        p = multiprocessing.Process(target=_worker_process_write, args=(str(tmp_path), i))
        processes.append(p)
        p.start()

    for p in processes:
        p.join(timeout=5)
        assert p.exitcode == 0, f"Processo falhou com código de saída {p.exitcode}"

    content = (tmp_path / ".memlog.md").read_text(encoding="utf-8")
    for i in range(8):
        assert f"story-proc-{i}" in content, f"Entrada do processo {i} ausente no arquivo"
        assert content.count(f"## [2026-08-12T23:{i:02d}:00Z]") == 1
