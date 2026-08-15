import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from executor.src.config import ExecutorSettings
from executor.src.validation import ValidationResult
from executor.src.github import (
    GitHubClient,
    GitHubAPIError,
    GitHubAuthError,
)


@pytest.fixture
def sample_validation_results():
    return [
        ValidationResult(
            command="pytest",
            exit_code=0,
            stdout="collected 10 items\n10 passed in 1.2s",
            stderr="",
            duration_seconds=1.2,
            passed=True
        ),
        ValidationResult(
            command="flake8",
            exit_code=0,
            stdout="",
            stderr="",
            duration_seconds=0.5,
            passed=True
        )
    ]


@pytest.fixture
def sample_review_summary():
    return {
        "status": "APPROVED",
        "findings_count": 2,
        "patches_applied": 2,
        "deferred_count": 0
    }


def test_generate_pr_title():
    client = GitHubClient(token="mock-token")
    title = client.generate_pr_title("3.2", "Geração e Abertura Semântica de Pull Requests")
    assert title == "feat(story-3.2): Geração e Abertura Semântica de Pull Requests"

    title_existing_prefix = client.generate_pr_title("3-2", "feat: already prefixed")
    assert title_existing_prefix == "feat(story-3-2): already prefixed"

    # Test story_id with redundant 'story-' prefix
    title_with_story_prefix = client.generate_pr_title("story-3.2", "Nova funcionalidade")
    assert title_with_story_prefix == "feat(story-3.2): Nova funcionalidade"


def test_format_semantic_pr_body(sample_validation_results, sample_review_summary):
    client = GitHubClient(token="mock-token")
    body = client.format_semantic_pr_body(
        story_id="3.2",
        title="Geração e Abertura Semântica de Pull Requests",
        phase_results=[
            {"phase": "coding", "exit_code": 0, "logs": "Coding completed successfully."},
            {"phase": "review", "exit_code": 0, "logs": "Code review passed with 0 findings."}
        ],
        validation_results=sample_validation_results,
        review_summary=sample_review_summary,
        project_item_id="PVTI_12345"
    )

    assert "## 🤖 AI Developer — Pull Request de Entrega" in body
    assert "Story 3.2" in body or "3.2 — Geração" in body
    assert "PVTI_12345" in body
    assert "Política Zero Deferred Work" in body
    assert "Débitos Diferidos:** 0" in body
    assert "2 aprovados / 0 falhas" in body
    assert "`pytest`" in body
    assert "`flake8`" in body
    assert "pronto para a revisão humana final" in body


@pytest.mark.asyncio
async def test_create_pull_request_success():
    settings = ExecutorSettings(
        GITHUB_TOKEN="ghp_mock_token_123",
        GITHUB_REPOSITORY="org/repo-target",
        PROJECT_ROOT="/tmp"
    )
    client = GitHubClient(settings=settings)

    mock_response_data = {
        "number": 42,
        "html_url": "https://github.com/org/repo-target/pull/42",
        "url": "https://api.github.com/repos/org/repo-target/pulls/42",
        "head": {"ref": "feature/story-3.2", "sha": "abcdef123456"},
        "base": {"ref": "main"}
    }

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 201
    mock_resp.json.return_value = mock_response_data
    mock_resp.is_error = False

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result = await client.create_pull_request(
            repo="org/repo-target",
            title="feat(story-3.2): Open PR",
            body="PR Body Content",
            head_branch="feature/story-3.2",
            base_branch="main"
        )

        assert result["pr_number"] == 42
        assert result["pr_url"] == "https://api.github.com/repos/org/repo-target/pulls/42"
        assert result["pr_html_url"] == "https://github.com/org/repo-target/pull/42"
        assert result["head_branch"] == "feature/story-3.2"
        assert result["base_branch"] == "main"
        assert result["commit_sha"] == "abcdef123456"

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert "Authorization" in call_kwargs["headers"]
        assert call_kwargs["headers"]["Authorization"] == "Bearer ghp_mock_token_123"
        assert call_kwargs["json"]["title"] == "feat(story-3.2): Open PR"
        assert call_kwargs["json"]["head"] == "feature/story-3.2"
        assert call_kwargs["json"]["base"] == "main"


@pytest.mark.asyncio
async def test_create_pull_request_missing_token_raises_auth_error():
    settings = ExecutorSettings(
        GITHUB_TOKEN=None,
        GITHUB_REPOSITORY="org/repo-target",
        PROJECT_ROOT="/tmp"
    )
    client = GitHubClient(settings=settings)

    with pytest.raises(GitHubAuthError) as exc_info:
        await client.create_pull_request(
            repo="org/repo-target",
            title="feat(story-3.2): Test",
            body="Body",
            head_branch="feature/test"
        )
    assert "token" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_create_pull_request_auth_error_401():
    settings = ExecutorSettings(
        GITHUB_TOKEN="invalid_token",
        GITHUB_REPOSITORY="org/repo-target",
        PROJECT_ROOT="/tmp"
    )
    client = GitHubClient(settings=settings)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 401
    mock_resp.text = "Bad credentials"
    mock_resp.is_error = True
    mock_resp.json.return_value = {"message": "Bad credentials"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(GitHubAuthError) as exc_info:
            await client.create_pull_request(
                repo="org/repo-target",
                title="feat(story-3.2): Test",
                body="Body",
                head_branch="feature/test"
            )
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_create_pull_request_api_error_422():
    settings = ExecutorSettings(
        GITHUB_TOKEN="ghp_mock_token_123",
        GITHUB_REPOSITORY="org/repo-target",
        PROJECT_ROOT="/tmp"
    )
    client = GitHubClient(settings=settings)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 422
    mock_resp.text = "Validation Failed: A pull request already exists"
    mock_resp.is_error = True
    mock_resp.json.return_value = {"message": "Validation Failed"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(GitHubAPIError) as exc_info:
            await client.create_pull_request(
                repo="org/repo-target",
                title="feat(story-3.2): Test",
                body="Body",
                head_branch="feature/test"
            )
        assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_pull_request_dry_run():
    settings = ExecutorSettings(
        GITHUB_TOKEN=None,
        GITHUB_REPOSITORY="org/repo-target",
        GITHUB_DRY_RUN=True,
        PROJECT_ROOT="/tmp"
    )
    client = GitHubClient(settings=settings)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        result = await client.create_pull_request(
            repo="org/repo-target",
            title="feat(story-3.2): Dry run test",
            body="Body",
            head_branch="feature/test"
        )
        mock_post.assert_not_called()
        assert result["dry_run"] is True
        assert result["pr_number"] > 0
        assert "pr_url" in result
        assert result["head_branch"] == "feature/test"


@pytest.mark.asyncio
async def test_update_project_card_status_success():
    settings = ExecutorSettings(
        GITHUB_TOKEN="ghp_mock_token_123",
        PROJECT_ROOT="/tmp"
    )
    client = GitHubClient(settings=settings)

    mock_graphql_resp = {
        "data": {
            "updateProjectV2ItemFieldValue": {
                "projectV2Item": {
                    "id": "PVTI_item123"
                }
            }
        }
    }

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_graphql_resp
    mock_resp.is_error = False

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result = await client.update_project_card_status(
            project_id="PVT_proj123",
            item_id="PVTI_item123",
            field_id="PVTF_status123",
            option_id="opt_in_review"
        )

        assert result["updated"] is True
        assert result["item_id"] == "PVTI_item123"

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert "query" in call_kwargs["json"]
        assert "variables" in call_kwargs["json"]
        assert call_kwargs["json"]["variables"]["projectId"] == "PVT_proj123"
        assert call_kwargs["json"]["variables"]["itemId"] == "PVTI_item123"


@pytest.mark.asyncio
async def test_update_project_card_status_graphql_error():
    settings = ExecutorSettings(
        GITHUB_TOKEN="ghp_mock_token_123",
        PROJECT_ROOT="/tmp"
    )
    client = GitHubClient(settings=settings)

    mock_graphql_resp = {
        "errors": [
            {"message": "Could not resolve to a ProjectV2Item with the ID 'PVTI_invalid'."}
        ]
    }

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_graphql_resp
    mock_resp.is_error = False

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(GitHubAPIError) as exc_info:
            await client.update_project_card_status(
                project_id="PVT_proj123",
                item_id="PVTI_invalid",
                field_id="PVTF_status123",
                option_id="opt_in_review"
            )
        assert "Could not resolve" in str(exc_info.value)


@pytest.mark.asyncio
async def test_update_project_card_status_dry_run():
    settings = ExecutorSettings(
        GITHUB_TOKEN=None,
        GITHUB_DRY_RUN=True,
        PROJECT_ROOT="/tmp"
    )
    client = GitHubClient(settings=settings)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        result = await client.update_project_card_status(
            project_id="PVT_proj123",
            item_id="PVTI_item123",
            field_id="PVTF_status123",
            option_id="opt_in_review"
        )
        mock_post.assert_not_called()
        assert result["updated"] is True
        assert result["dry_run"] is True
        assert result["item_id"] == "PVTI_item123"


def test_format_semantic_pr_body_with_raw_dicts():
    """Valida formatação do corpo do PR quando validações são fornecidas como dicionários brutos."""
    client = GitHubClient(token="mock-token")
    raw_validation = [
        {"command": "pytest tests/", "passed": True, "exit_code": 0},
        {"command": "flake8 .", "passed": False, "exit_code": 1}
    ]
    body = client.format_semantic_pr_body(
        story_id="3.2",
        title="Dict test",
        validation_results=raw_validation
    )
    assert "1 aprovados / 1 falhas" in body
    assert "`pytest tests/`: ✅ PASSED" in body
    assert "`flake8 .`: ❌ FAILED (exit 1)" in body


@pytest.mark.asyncio
async def test_create_pull_request_cleans_repo_name():
    """Valida limpeza de URLs e sufixos .git ao abrir PR."""
    settings = ExecutorSettings(GITHUB_TOKEN="ghp_test", PROJECT_ROOT="/tmp")
    client = GitHubClient(settings=settings)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "number": 10,
        "url": "https://api.github.com/repos/org/repo/pulls/10",
        "html_url": "https://github.com/org/repo/pull/10",
        "head": {"ref": "feature/story-3.2", "sha": "sha123"},
        "base": {"ref": "main"}
    }
    mock_resp.is_error = False

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        await client.create_pull_request(
            repo="https://github.com/org/repo.git/",
            title="feat(story-3.2): Clean repo test",
            body="body",
            head_branch="feature/story-3.2"
        )
        assert mock_post.call_args.args[0] == "https://api.github.com/repos/org/repo/pulls"


@pytest.mark.asyncio
async def test_update_project_card_enterprise_graphql_url():
    """Valida resolução correta do endpoint GraphQL para GitHub Enterprise."""
    settings = ExecutorSettings(
        GITHUB_TOKEN="ghp_ent_token",
        GITHUB_API_URL="https://github.enterprise.com/api/v3",
        PROJECT_ROOT="/tmp"
    )
    client = GitHubClient(settings=settings)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "item1"}}}}
    mock_resp.is_error = False

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        await client.update_project_card_status(
            project_id="P1",
            item_id="I1",
            field_id="F1",
            option_id="O1"
        )
        assert mock_post.call_args.args[0] == "https://github.enterprise.com/api/graphql"

