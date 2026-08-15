import os
import asyncio
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from executor.src.config import ExecutorSettings
from executor.src.worker import ExecutorWorker
from executor.src.sandbox import DockerSandboxManager
from executor.src.validation import ValidationResult
from executor.src.exceptions import PromptTemplateNotFoundError
from persistence.src.repository import EventRecord


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.claim_event = AsyncMock()
    repo.complete_event = AsyncMock()
    repo.fail_event = AsyncMock()
    repo.add_audit_log = AsyncMock()
    repo.save_agent_memory = AsyncMock(return_value={"id": "mem-1"})
    repo.get_agent_memory = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_sandbox():
    sandbox = MagicMock(spec=DockerSandboxManager)
    sandbox.execute_job.return_value = {
        "exit_code": 0,
        "logs": "Execution completed successfully\n",
        "container_id": "c12345"
    }
    return sandbox


@pytest.fixture
def settings():
    return ExecutorSettings(
        POLL_INTERVAL=0.01,
        MAX_POLL_INTERVAL=0.1,
        BACKOFF_FACTOR=2.0,
        WORKER_ID="test-worker-1"
    )


@pytest.mark.asyncio
async def test_worker_claim_and_complete(mock_repo, mock_sandbox, settings):
    event = EventRecord(
        id="1",
        event_id="evt-100",
        event_type="workflow.execution",
        status="PROCESSING",
        payload={"command": "python -c 'print(42)'", "image": "python:3.12-slim", "phase": "coding", "story_id": "2-3-story"}
    )

    mock_repo.claim_event.side_effect = [event, None]

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    mock_repo.claim_event.assert_called()
    assert mock_sandbox.execute_job.called
    first_call_kwargs = mock_sandbox.execute_job.call_args_list[0].kwargs
    assert first_call_kwargs["command"] == "python -c 'print(42)'"
    assert first_call_kwargs["image"] == "python:3.12-slim"
    assert first_call_kwargs["context_bundle"]["phase"] == "coding"

    mock_repo.save_agent_memory.assert_called_once()
    # F7: verificar que audit log VALIDATION_PASSED foi emitido no fluxo de sucesso
    validation_passed_calls = [
        c for c in mock_repo.add_audit_log.call_args_list
        if c.kwargs.get("action") == "VALIDATION_PASSED"
    ]
    assert len(validation_passed_calls) == 1, "Audit log VALIDATION_PASSED deve ser emitido no fluxo de sucesso"
    assert validation_passed_calls[0].kwargs.get("details", {}).get("story_id") == "2-3-story"

    mock_repo.complete_event.assert_called_once()
    call_args = mock_repo.complete_event.call_args
    assert call_args.args[0] == "evt-100"
    assert call_args.args[1] == "test-worker-1"
    assert call_args.kwargs["details"]["exit_code"] == 0


@pytest.mark.asyncio
async def test_worker_missing_prompt_template_fails_gracefully(mock_repo, mock_sandbox, settings):
    event = EventRecord(
        id="2",
        event_id="evt-200",
        event_type="workflow.execution",
        status="PROCESSING",
        payload={"command": "python script.py", "phase": "nonexistent_phase"}
    )
    mock_repo.claim_event.side_effect = [event, None]

    with patch("executor.src.context_loader.ContextLoader.build_context_bundle") as mock_build:
        mock_build.side_effect = PromptTemplateNotFoundError("Prompt obrigatório ausente: template para a fase 'nonexistent_phase'")

        worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

        task = asyncio.create_task(worker.start())
        await asyncio.sleep(0.05)
        worker.stop()
        await task

        mock_sandbox.execute_job.assert_not_called()
        mock_repo.fail_event.assert_called_once()
        fail_args = mock_repo.fail_event.call_args
        assert fail_args.args[0] == "evt-200"
        assert "Prompt obrigatório ausente" in fail_args.kwargs["error_message"]


@pytest.mark.asyncio
async def test_worker_claim_and_fail(mock_repo, mock_sandbox, settings):
    event = EventRecord(
        id="3",
        event_id="evt-300",
        event_type="workflow.execution",
        status="PROCESSING",
        payload={"command": "invalid command"}
    )
    mock_sandbox.execute_job.side_effect = RuntimeError("Sandbox container creation failed")
    mock_repo.claim_event.side_effect = [event, None]

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    mock_repo.fail_event.assert_called_once()
    call_args = mock_repo.fail_event.call_args
    assert call_args.args[0] == "evt-300"
    assert call_args.args[1] == "test-worker-1"
    assert "Sandbox container creation failed" in call_args.kwargs["error_message"]


@pytest.mark.asyncio
async def test_worker_backoff_logic(mock_repo, mock_sandbox, settings):
    mock_repo.claim_event.return_value = None

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)
    assert worker.current_poll_interval == settings.POLL_INTERVAL

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.06)
    worker.stop()
    await task

    assert worker.current_poll_interval > settings.POLL_INTERVAL
    assert worker.current_poll_interval <= settings.MAX_POLL_INTERVAL


@pytest.mark.asyncio
async def test_worker_graceful_shutdown(mock_repo, mock_sandbox, settings):
    mock_repo.claim_event.return_value = None
    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)
    assert not worker.running

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.01)
    assert worker.running

    worker.stop()
    await task
    assert not worker.running


@pytest.mark.asyncio
async def test_worker_invalid_payload(mock_repo, mock_sandbox, settings):
    event = MagicMock()
    event.event_id = "evt-400"
    event.event_type = "workflow.execution"
    event.payload = "raw-string-payload"
    mock_repo.claim_event.side_effect = [event, None]

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    assert mock_sandbox.execute_job.called
    first_call_kwargs = mock_sandbox.execute_job.call_args_list[0].kwargs
    assert first_call_kwargs["command"] == "echo 'Nenhum comando especificado'"
    assert first_call_kwargs["context_bundle"] is not None
    assert first_call_kwargs["context_bundle"]["phase"] == "coding"
    mock_repo.complete_event.assert_called_once()


@pytest.mark.asyncio
async def test_worker_multi_phase_sequential_execution(mock_repo, mock_sandbox, settings):
    event = EventRecord(
        id="5",
        event_id="evt-500",
        event_type="workflow.execution",
        status="PROCESSING",
        payload={
            "command": "python run.py",
            "image": "python:3.12-slim",
            "phases": ["coding", "review"]
        }
    )
    mock_repo.claim_event.side_effect = [event, None]
    mock_sandbox.execute_job.return_value = {"exit_code": 0, "logs": "Phase OK", "container_id": "c-123"}

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    # 2 execution phases + 1 validation command = 3 execute_job calls
    assert mock_sandbox.execute_job.call_count == 3
    calls = mock_sandbox.execute_job.call_args_list
    assert calls[0].kwargs["context_bundle"]["phase"] == "coding"
    assert calls[1].kwargs["context_bundle"]["phase"] == "review"

    mock_repo.complete_event.assert_called_once()
    complete_details = mock_repo.complete_event.call_args.kwargs["details"]
    assert len(complete_details["phases"]) == 2
    assert complete_details["phases"][0]["phase"] == "coding"
    assert complete_details["phases"][1]["phase"] == "review"


@pytest.mark.asyncio
async def test_worker_validation_failure_blocks_completion(mock_repo, mock_sandbox, settings):
    event = EventRecord(
        id="6",
        event_id="evt-600",
        event_type="workflow.execution",
        status="PROCESSING",
        payload={
            "command": "python code.py",
            "story_id": "2-3-pipeline-failure-test"
        }
    )
    mock_repo.claim_event.side_effect = [event, None]

    # Phases: coding=0, review=0, then validation=1 (fails)
    mock_sandbox.execute_job.side_effect = [
        {"exit_code": 0, "logs": "Coding completed OK", "container_id": "c-1"},
        {"exit_code": 0, "logs": "Review completed OK", "container_id": "c-2"},
        {"exit_code": 1, "logs": "Pytest failed: 3 tests errored", "container_id": "c-3"}
    ]

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    # complete_event should NOT be called
    mock_repo.complete_event.assert_not_called()
    # fail_event SHOULD be called with validation failure
    mock_repo.fail_event.assert_called_once()
    fail_args = mock_repo.fail_event.call_args
    assert fail_args.args[0] == "evt-600"
    assert "Validação pré-entrega falhou" in fail_args.kwargs["error_message"]

    # Audit log VALIDATION_FAILED should be recorded
    audit_calls = [c for c in mock_repo.add_audit_log.call_args_list if c.kwargs.get("action") == "VALIDATION_FAILED"]
    assert len(audit_calls) == 1

    # Daily summary memory should still be recorded for the failed validation
    mock_repo.save_agent_memory.assert_called_once()
    mem_call = mock_repo.save_agent_memory.call_args.kwargs
    assert mem_call["story_id"] == "2-3-pipeline-failure-test"
    assert mem_call["content"]["status"] == "VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_worker_review_phase_failure_triggers_audit_and_stops(mock_repo, mock_sandbox, settings):
    event = EventRecord(
        id="7",
        event_id="evt-700",
        event_type="workflow.execution",
        status="PROCESSING",
        payload={
            "command": "python code.py",
            "story_id": "3-1-review-fail-test",
            "phases": ["coding", "review"]
        }
    )
    mock_repo.claim_event.side_effect = [event, None]

    # Coding phase succeeds, Review phase fails
    mock_sandbox.execute_job.side_effect = [
        {"exit_code": 0, "logs": "Coding OK", "container_id": "c-1"},
        {"exit_code": 1, "logs": "Review found syntax errors and unhandled exceptions", "container_id": "c-2"}
    ]

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    mock_repo.complete_event.assert_not_called()
    mock_repo.fail_event.assert_called_once()
    fail_args = mock_repo.fail_event.call_args
    assert "Job da fase 'review' encerrado com erro" in fail_args.kwargs["error_message"]

    # Check that CODE_REVIEW_FAILED audit log was recorded
    review_failed_logs = [c for c in mock_repo.add_audit_log.call_args_list if c.kwargs.get("action") == "CODE_REVIEW_FAILED"]
    assert len(review_failed_logs) == 1
    assert review_failed_logs[0].kwargs.get("details", {}).get("story_id") == "3-1-review-fail-test"


@pytest.mark.asyncio
async def test_worker_full_story_3_1_workflow_audit_and_readiness(mock_repo, mock_sandbox, settings):
    event = EventRecord(
        id="8",
        event_id="evt-800",
        event_type="workflow.execution",
        status="PROCESSING",
        payload={
            "command": "python dev_pipeline.py",
            "story_id": "3-1-autonomous-dev",
            "review_summary": {
                "status": "APPROVED",
                "findings_count": 3,
                "patches_applied": 3,
                "deferred_count": 0
            }
        }
    )
    mock_repo.claim_event.side_effect = [event, None]
    # Default flow: coding(0), review(0), validation(0)
    mock_sandbox.execute_job.side_effect = [
        {"exit_code": 0, "logs": "Coding phase completed", "container_id": "c-code"},
        {"exit_code": 0, "logs": "Review phase completed (3 patches applied)", "container_id": "c-rev"},
        {"exit_code": 0, "logs": "Pytest 87 passed", "container_id": "c-val"}
    ]

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    # Check audit log trail
    audit_actions = [c.kwargs.get("action") for c in mock_repo.add_audit_log.call_args_list]
    assert "WORKFLOW_PHASE_STARTED" in audit_actions
    assert "WORKFLOW_PHASE_COMPLETED" in audit_actions
    assert "CODE_REVIEW_PASSED" in audit_actions
    assert "VALIDATION_PASSED" in audit_actions

    # Check complete_event details
    mock_repo.complete_event.assert_called_once()
    complete_details = mock_repo.complete_event.call_args.kwargs["details"]
    assert complete_details["ready_for_pr"] is True
    assert complete_details["review_summary"]["patches_applied"] == 3
    assert complete_details["review_summary"]["deferred_count"] == 0
    assert len(complete_details["phases"]) == 2

    # Check memory persistence
    mock_repo.save_agent_memory.assert_called_once()
    mem_content = mock_repo.save_agent_memory.call_args.kwargs["content"]
    assert mem_content["review_summary"]["status"] == "APPROVED"
    assert mem_content["review_summary"]["patches_applied"] == 3

