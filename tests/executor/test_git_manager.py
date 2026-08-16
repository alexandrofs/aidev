import pytest
from executor.src.config import ExecutorSettings
from executor.src.git_manager import GitManager


def test_git_manager_authenticated_url():
    settings = ExecutorSettings(GITHUB_TOKEN="ghp_test123")
    git_manager = GitManager(settings=settings)

    url = git_manager.get_authenticated_repo_url("alexandrofs/aidev")
    assert url == "https://x-access-token:ghp_test123@github.com/alexandrofs/aidev.git"

    # Sem token
    url_no_token = git_manager.get_authenticated_repo_url("alexandrofs/aidev", token="")
    assert url_no_token == "https://github.com/alexandrofs/aidev.git"


def test_git_manager_setup_commands():
    settings = ExecutorSettings(
        GITHUB_TOKEN="ghp_test123",
        GITHUB_REPOSITORY="org/repo",
        GITHUB_BASE_BRANCH="main",
        GIT_AUTHOR_NAME="Bot Dev",
        GIT_AUTHOR_EMAIL="bot@aidev.com"
    )
    git_manager = GitManager(settings=settings)

    cmds = git_manager.get_setup_commands()
    assert any("safe.directory /workspace" in c for c in cmds)
    assert any("user.name 'Bot Dev'" in c for c in cmds)
    assert any("user.email 'bot@aidev.com'" in c for c in cmds)
    assert any("git clone" in c and "https://x-access-token:ghp_test123@github.com/org/repo.git" in c for c in cmds)


def test_git_manager_branch_and_push_commands():
    settings = ExecutorSettings(GITHUB_TOKEN="ghp_test123")
    git_manager = GitManager(settings=settings)

    branch_cmds = git_manager.get_branch_checkout_commands("feature/story-10")
    assert branch_cmds == ["cd /workspace && git checkout -B feature/story-10"]

    push_cmds = git_manager.get_commit_and_push_commands(
        branch_name="feature/story-10",
        commit_message="feat(10): add payment module",
        repository="org/repo"
    )
    assert any("git add -A" in c for c in push_cmds)
    assert any("git commit -m 'feat(10): add payment module'" in c for c in push_cmds)
    assert any("git push -u" in c and "feature/story-10" in c for c in push_cmds)
