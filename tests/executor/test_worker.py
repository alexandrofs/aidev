import os
import asyncio
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from executor.src.config import ExecutorSettings
from executor.src.worker import ExecutorWorker, extract_story_id_from_issue
from executor.src.sandbox import DockerSandboxManager, SandboxSession
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
def mock_session():
    session = MagicMock()
    session.id = "c12345"
    session.exec.return_value = {
        "exit_code": 0,
        "logs": "Execution completed successfully\n",
        "container_id": "c12345"
    }
    session.close.return_value = None
    return session


@pytest.fixture
def mock_sandbox(mock_session):
    sandbox = MagicMock(spec=DockerSandboxManager)
    sandbox.create_session.return_value = mock_session
    sandbox.execute_job.return_value = {
        "exit_code": 0,
        "logs": "Execution completed successfully\n",
        "container_id": "c12345"
    }
    return sandbox


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return ExecutorSettings(
        POLL_INTERVAL=0.01,
        MAX_POLL_INTERVAL=0.1,
        BACKOFF_FACTOR=2.0,
        WORKER_ID="test-worker-1",
        GITHUB_REPOSITORY=None,
        GITHUB_TOKEN=None
    )


@pytest.mark.asyncio
async def test_worker_claim_and_complete(mock_repo, mock_sandbox, mock_session, settings):
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
    assert mock_sandbox.create_session.called
    assert mock_session.exec.called

    mock_repo.save_agent_memory.assert_called_once()
    mock_repo.complete_event.assert_called_once()
    call_args = mock_repo.complete_event.call_args
    assert call_args.args[0] == "evt-100"
    assert call_args.args[1] == "test-worker-1"
    assert call_args.kwargs["details"]["container_id"] == "c12345"


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

        mock_sandbox.create_session.assert_not_called()
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
    mock_sandbox.create_session.side_effect = RuntimeError("Sandbox container creation failed")
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
async def test_worker_invalid_payload(mock_repo, mock_sandbox, mock_session, settings):
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

    assert mock_sandbox.create_session.called
    mock_repo.complete_event.assert_called_once()


@pytest.mark.asyncio
async def test_worker_multi_phase_sequential_execution(mock_repo, mock_sandbox, mock_session, settings):
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
    mock_session.exec.return_value = {"exit_code": 0, "logs": "Phase OK", "container_id": "c-123"}

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    # Session created once
    assert mock_sandbox.create_session.call_count == 1
    # Multiple exec calls on same session
    assert mock_session.exec.call_count >= 2

    mock_repo.complete_event.assert_called_once()


@pytest.mark.asyncio
async def test_worker_validation_failure_blocks_completion(mock_repo, mock_sandbox, mock_session, settings):
    event = EventRecord(
        id="6",
        event_id="evt-600",
        event_type="workflow.execution",
        status="PROCESSING",
        payload={
            "command": "python code.py",
            "story_id": "2-3-phase-failure-test"
        }
    )
    mock_repo.claim_event.side_effect = [event, None]

    # Setup git ok, coding fails
    mock_session.exec.side_effect = [
        {"exit_code": 0, "logs": "Git setup 1", "container_id": "c-1"},
        {"exit_code": 0, "logs": "Git setup 2", "container_id": "c-1"},
        {"exit_code": 0, "logs": "Git setup 3", "container_id": "c-1"},
        {"exit_code": 0, "logs": "Branch ok", "container_id": "c-1"},
        {"exit_code": 1, "logs": "Coding phase failed: tests or syntax errors", "container_id": "c-1"}
    ]

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    mock_repo.complete_event.assert_not_called()
    mock_repo.fail_event.assert_called_once()
    fail_args = mock_repo.fail_event.call_args
    assert fail_args.args[0] == "evt-600"
    assert "falhou no sandbox" in fail_args.kwargs["error_message"]


@pytest.mark.asyncio
async def test_worker_review_phase_failure_triggers_audit_and_stops(mock_repo, mock_sandbox, mock_session, settings):
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

    # Setup git ok, Coding phase succeeds, Review phase fails
    mock_session.exec.side_effect = [
        {"exit_code": 0, "logs": "Git setup 1", "container_id": "c-1"},
        {"exit_code": 0, "logs": "Git setup 2", "container_id": "c-1"},
        {"exit_code": 0, "logs": "Git setup 3", "container_id": "c-1"},
        {"exit_code": 0, "logs": "Branch ok", "container_id": "c-1"},
        {"exit_code": 0, "logs": "Coding OK", "container_id": "c-1"},
        {"exit_code": 1, "logs": "Review found syntax errors", "container_id": "c-1"}
    ]

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    mock_repo.complete_event.assert_not_called()
    mock_repo.fail_event.assert_called_once()
    fail_args = mock_repo.fail_event.call_args
    assert "Fase 'review' falhou no sandbox" in fail_args.kwargs["error_message"]


@pytest.mark.asyncio
async def test_worker_full_story_3_1_workflow_audit_and_readiness(mock_repo, mock_sandbox, mock_session, settings):
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

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    audit_actions = [c.kwargs.get("action") for c in mock_repo.add_audit_log.call_args_list]
    assert "WORKFLOW_PHASE_STARTED" in audit_actions
    assert "WORKFLOW_PHASE_COMPLETED" in audit_actions

    mock_repo.complete_event.assert_called_once()
    mock_repo.save_agent_memory.assert_called_once()
    mem_content = mock_repo.save_agent_memory.call_args.kwargs["content"]
    assert mem_content["review_summary"]["status"] == "APPROVED"
    assert mem_content["review_summary"]["patches_applied"] == 3


@pytest.mark.asyncio
async def test_worker_successful_pr_creation_and_audit_logs(mock_repo, mock_sandbox, mock_session, settings):
    from executor.src.github import GitHubClient

    mock_github = MagicMock(spec=GitHubClient)
    mock_github.generate_pr_title.return_value = "feat(story-3.2): Geracao e Abertura Semantica de PR"
    mock_github.format_semantic_pr_body.return_value = "## 🤖 AI Developer — Pull Request de Entrega"
    mock_github.create_pull_request = AsyncMock(return_value={
        "pr_number": 42,
        "pr_url": "https://api.github.com/repos/org/repo/pulls/42",
        "pr_html_url": "https://github.com/org/repo/pull/42",
        "head_branch": "feature/story-3.2",
        "base_branch": "main",
        "commit_sha": "abc123sha"
    })

    event = EventRecord(
        id="9",
        event_id="evt-900",
        event_type="workflow.execution",
        status="PROCESSING",
        payload={
            "command": "python run.py",
            "story_id": "3.2",
            "repository": "org/repo",
            "branch": "feature/story-3.2"
        }
    )
    mock_repo.claim_event.side_effect = [event, None]

    worker = ExecutorWorker(
        repo=mock_repo,
        sandbox_manager=mock_sandbox,
        github_client=mock_github,
        settings=settings
    )

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    mock_github.generate_pr_title.assert_called_once()
    mock_github.format_semantic_pr_body.assert_called_once()
    mock_github.create_pull_request.assert_called_once()

    audit_actions = [c.kwargs.get("action") for c in mock_repo.add_audit_log.call_args_list]
    assert "PR_CREATED" in audit_actions

    mock_repo.complete_event.assert_called_once()
    mock_repo.save_agent_memory.assert_called_once()
    mem_content = mock_repo.save_agent_memory.call_args.kwargs["content"]
    assert mem_content["pr_number"] == 42
    assert mem_content["pull_request_status"] == "OPEN"


@pytest.mark.asyncio
async def test_worker_projects_card_updated_when_project_item_present(mock_repo, mock_sandbox, mock_session, settings):
    from executor.src.github import GitHubClient

    mock_github = MagicMock(spec=GitHubClient)
    mock_github.generate_pr_title.return_value = "feat(story-3.2): Title"
    mock_github.format_semantic_pr_body.return_value = "Body"
    mock_github.create_pull_request = AsyncMock(return_value={
        "pr_number": 101,
        "pr_url": "https://api.github.com/repos/org/repo/pulls/101",
        "pr_html_url": "https://github.com/org/repo/pull/101",
        "head_branch": "feature/story-3.2",
        "base_branch": "main",
        "commit_sha": "def456"
    })
    mock_github.update_project_card_status = AsyncMock(return_value={"updated": True, "item_id": "PVTI_item999"})

    event = EventRecord(
        id="10",
        event_id="evt-1000",
        event_type="workflow.execution",
        status="PROCESSING",
        payload={
            "command": "python run.py",
            "story_id": "3.2",
            "repository": "org/repo",
            "project_id": "PVT_proj777",
            "project_item_id": "PVTI_item999",
            "project_field_id": "PVTF_status",
            "project_option_id": "opt_review"
        }
    )
    mock_repo.claim_event.side_effect = [event, None]

    worker = ExecutorWorker(
        repo=mock_repo,
        sandbox_manager=mock_sandbox,
        github_client=mock_github,
        settings=settings
    )

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    mock_github.create_pull_request.assert_called_once()
    mock_repo.complete_event.assert_called_once()


@pytest.mark.asyncio
async def test_worker_pr_failure_emits_pr_failed_audit_and_fails_event(mock_repo, mock_sandbox, mock_session, settings):
    from executor.src.github import GitHubClient, GitHubAPIError

    mock_github = MagicMock(spec=GitHubClient)
    mock_github.generate_pr_title.return_value = "feat(story-3.2): Title"
    mock_github.format_semantic_pr_body.return_value = "Body"
    mock_github.create_pull_request = AsyncMock(side_effect=GitHubAPIError("403 Forbidden - Rate limit exceeded"))

    event = EventRecord(
        id="11",
        event_id="evt-1100",
        event_type="workflow.execution",
        status="PROCESSING",
        payload={
            "command": "python run.py",
            "story_id": "3.2",
            "repository": "org/repo"
        }
    )
    mock_repo.claim_event.side_effect = [event, None]

    worker = ExecutorWorker(
        repo=mock_repo,
        sandbox_manager=mock_sandbox,
        github_client=mock_github,
        settings=settings
    )

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    audit_actions = [c.kwargs.get("action") for c in mock_repo.add_audit_log.call_args_list]
    assert "PR_FAILED" in audit_actions
    mock_repo.complete_event.assert_not_called()
    mock_repo.fail_event.assert_called_once()
    fail_args = mock_repo.fail_event.call_args
    assert fail_args.args[0] == "evt-1100"
    assert "Falha na abertura de Pull Request no GitHub" in fail_args.kwargs["error_message"]


def test_worker_load_target_repo_config(tmp_path):
    # 1. Sem arquivo de manifesto
    assert ExecutorWorker.load_target_repo_config(str(tmp_path)) == {}
    assert ExecutorWorker.load_target_repo_config(None) == {}

    # 2. Com .aidev.yaml
    yaml_content = """
version: "1"
github:
  repository: "myorg/myapp"
  project_id: "PVT_kwDO_TARGET"
validation:
  commands:
    - "mvn test"
"""
    yaml_file = tmp_path / ".aidev.yaml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    cfg = ExecutorWorker.load_target_repo_config(str(tmp_path))
    assert cfg["version"] == "1"
    assert cfg["github"]["project_id"] == "PVT_kwDO_TARGET"
    assert cfg["validation"]["commands"] == ["mvn test"]


def test_extract_story_id_from_issue():
    # 1. Padrão "Story Key: 5-2-time-to-goal-motivational-clock"
    issue_1 = {
        "number": 42,
        "body": "Por favor implementar esta funcionalidade.\n\nStory Key: 5-2-time-to-goal-motivational-clock\n\nDetalhes..."
    }
    assert extract_story_id_from_issue(issue_1, "fallback-1") == "5-2-time-to-goal-motivational-clock"

    # 2. Padrão "Story: 1-4-adicao-coluna-repository" com ponto final no fim
    issue_2 = {
        "id": 1001,
        "body": "Story: 1-4-adicao-coluna-repository.\nMais texto"
    }
    assert extract_story_id_from_issue(issue_2, "fallback-2") == "1-4-adicao-coluna-repository"

    # 3. Fallback sem Story Key no body -> prioriza issue.number
    issue_3 = {"id": 88, "number": 12, "body": "Issue sem chave de história"}
    assert extract_story_id_from_issue(issue_3, "fallback-3") == "issue-12"

    # 4. Fallback apenas com id
    issue_4 = {"id": 88, "body": "Apenas ID"}
    assert extract_story_id_from_issue(issue_4, "fallback-4") == "issue-88"

    # 5. Fallback apenas com number
    issue_5 = {"number": 99, "body": "Apenas número"}
    assert extract_story_id_from_issue(issue_5, "fallback-5") == "issue-99"


@pytest.mark.asyncio
async def test_worker_issue_story_key_extraction_and_feature_branch(mock_repo, mock_sandbox, mock_session, settings):
    """[AC 6, 7] Worker extrai Story Key do body e cria branch feature/<codigo_historia>."""
    event = EventRecord(
        id="12",
        event_id="evt-issue-story-key",
        event_type="issues",
        status="PROCESSING",
        repository="org/custom-repo",
        payload={
            "action": "labeled",
            "issue": {
                "number": 55,
                "body": "Implementar timer motivational.\nStory Key: 5-2-time-to-goal-motivational-clock"
            }
        }
    )
    mock_repo.claim_event.side_effect = [event, None]

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    with patch.object(worker.git_manager, "get_branch_checkout_commands", wraps=worker.git_manager.get_branch_checkout_commands) as mock_branch_cmds:
        task = asyncio.create_task(worker.start())
        await asyncio.sleep(0.05)
        worker.stop()
        await task

        mock_branch_cmds.assert_called_once_with("feature/5-2-time-to-goal-motivational-clock")
        mock_repo.complete_event.assert_called_once()


@pytest.mark.asyncio
async def test_worker_issue_fallback_and_feature_branch(mock_repo, mock_sandbox, mock_session, settings):
    """[AC 6, 7] Worker sem Story Key adota fallback issue-<id> e branch feature/issue-<id>."""
    event = EventRecord(
        id="13",
        event_id="evt-issue-fallback",
        event_type="issues",
        status="PROCESSING",
        repository="org/custom-repo",
        payload={
            "action": "labeled",
            "issue": {
                "number": 77,
                "body": "Descrição genérica sem chave."
            }
        }
    )
    mock_repo.claim_event.side_effect = [event, None]

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    with patch.object(worker.git_manager, "get_branch_checkout_commands", wraps=worker.git_manager.get_branch_checkout_commands) as mock_branch_cmds:
        task = asyncio.create_task(worker.start())
        await asyncio.sleep(0.05)
        worker.stop()
        await task

        mock_branch_cmds.assert_called_once_with("feature/issue-77")
        mock_repo.complete_event.assert_called_once()


@pytest.mark.asyncio
async def test_worker_repository_priority_resolution(mock_repo, mock_sandbox, mock_session, settings):
    """[AC 9] Leitura prioritária de event.repository -> payload.repository -> settings.GITHUB_REPOSITORY."""
    # 1. event.repository tem prioridade máxima
    event_1 = EventRecord(
        id="14",
        event_id="evt-repo-priority-1",
        event_type="issues",
        status="PROCESSING",
        repository="org/repo-from-event-record",
        payload={"repository": "org/repo-from-payload"}
    )
    mock_repo.claim_event.side_effect = [event_1, None]

    worker = ExecutorWorker(repo=mock_repo, sandbox_manager=mock_sandbox, settings=settings)

    with patch.object(worker.git_manager, "get_setup_commands", wraps=worker.git_manager.get_setup_commands) as mock_setup_cmds:
        task = asyncio.create_task(worker.start())
        await asyncio.sleep(0.05)
        worker.stop()
        await task

        call_kwargs = mock_setup_cmds.call_args.kwargs
        assert call_kwargs["repository"] == "org/repo-from-event-record"

    # 2. Fallback secundário para payload.repository quando event.repository for None
    mock_repo.claim_event.reset_mock()
    event_2 = EventRecord(
        id="15",
        event_id="evt-repo-priority-2",
        event_type="issues",
        status="PROCESSING",
        repository=None,
        payload={"repository": "org/repo-from-payload"}
    )
    mock_repo.claim_event.side_effect = [event_2, None]

    with patch.object(worker.git_manager, "get_setup_commands", wraps=worker.git_manager.get_setup_commands) as mock_setup_cmds_2:
        task = asyncio.create_task(worker.start())
        await asyncio.sleep(0.05)
        worker.stop()
        await task

        call_kwargs_2 = mock_setup_cmds_2.call_args.kwargs
        assert call_kwargs_2["repository"] == "org/repo-from-payload"


