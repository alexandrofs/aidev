import os
import shutil
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from executor.src.config import ExecutorSettings, settings as global_settings

logger = logging.getLogger(__name__)


class GitManager:
    """
    Gerenciador de operações Git para o Sandbox do AI Developer.
    Suporta clone autenticado, criação de branches, commits e push.
    """

    def __init__(self, settings: Optional[ExecutorSettings] = None):
        self.settings = settings or global_settings

    def get_authenticated_repo_url(self, repository: Any, token: Optional[str] = None) -> str:
        """Gera a URL HTTPS autenticada para o repositório."""
        auth_token = self.settings.GITHUB_TOKEN if token is None else token
        if isinstance(repository, dict):
            repo_str = repository.get("full_name") or repository.get("name") or repository.get("html_url") or ""
        else:
            repo_str = str(repository or "")
        repo_clean = repo_str.replace("https://github.com/", "").strip("/")
        if auth_token:
            return f"https://x-access-token:{auth_token}@github.com/{repo_clean}.git"
        return f"https://github.com/{repo_clean}.git"

    def get_setup_commands(
        self,
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        token: Optional[str] = None,
        working_dir: str = "/workspace"
    ) -> list[str]:
        """
        Retorna comandos de terminal para clonar e configurar o Git no workspace do container.
        """
        repo_name = repository or self.settings.GITHUB_REPOSITORY
        if not repo_name:
            return [
                f"git config --global --add safe.directory {working_dir}",
                f"git config --global user.name '{self.settings.GIT_AUTHOR_NAME}'",
                f"git config --global user.email '{self.settings.GIT_AUTHOR_EMAIL}'"
            ]

        auth_url = self.get_authenticated_repo_url(repo_name, token=token)
        base_branch = branch or self.settings.GITHUB_BASE_BRANCH

        return [
            f"git config --global --add safe.directory {working_dir}",
            f"git config --global user.name '{self.settings.GIT_AUTHOR_NAME}'",
            f"git config --global user.email '{self.settings.GIT_AUTHOR_EMAIL}'",
            f"if [ ! -d '{working_dir}/.git' ]; then git clone --depth 50 -b {base_branch} '{auth_url}' {working_dir} 2>/dev/null || git clone '{auth_url}' {working_dir}; fi"
        ]

    def get_branch_checkout_commands(self, branch_name: str, working_dir: str = "/workspace") -> list[str]:
        """Retorna comandos para criar ou mudar para o feature branch."""
        return [
            f"cd {working_dir} && git checkout -B {branch_name}"
        ]

    def get_commit_and_push_commands(
        self,
        branch_name: str,
        commit_message: str,
        repository: Optional[str] = None,
        token: Optional[str] = None,
        working_dir: str = "/workspace"
    ) -> list[str]:
        """Retorna comandos para comitar alterações e realizar o git push."""
        repo_name = repository or self.settings.GITHUB_REPOSITORY
        auth_url = self.get_authenticated_repo_url(repo_name, token=token) if repo_name else "origin"
        escaped_msg = commit_message.replace("'", "'\"'\"'")

        return [
            f"cd {working_dir} && git add -A",
            f"cd {working_dir} && git diff --staged --quiet || git commit -m '{escaped_msg}'",
            f"cd {working_dir} && git push -u '{auth_url}' {branch_name} --force"
        ]
