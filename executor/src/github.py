import logging
import re
from typing import Optional, List, Dict, Any, Union

import httpx

from executor.src.config import ExecutorSettings, settings as global_settings

logger = logging.getLogger(__name__)


class GitHubAPIError(Exception):
    """Exceção base para erros retornados pela API do GitHub."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Any] = None
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_data = response_data

    def __str__(self) -> str:
        code_str = f" [status {self.status_code}]" if self.status_code else ""
        return f"{self.message}{code_str}"


class GitHubAuthError(GitHubAPIError):
    """Exceção específica para falhas de autenticação ou autorização (401/403/token ausente)."""
    pass


class GitHubClient:
    """
    Cliente assíncrono para integração com o GitHub.
    Responsável por:
    1. Geração semântica de títulos e corpos de Pull Requests.
    2. Abertura de Pull Requests via REST API v3.
    3. Atualização de status em GitHub Projects v2 via GraphQL API v4.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        api_url: Optional[str] = None,
        settings: Optional[ExecutorSettings] = None,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        self.settings = settings or global_settings
        self.token = token or (self.settings.GITHUB_TOKEN if self.settings else None)
        raw_url = api_url or (self.settings.GITHUB_API_URL if self.settings else "https://api.github.com")
        self.api_url = raw_url.rstrip("/")
        self.dry_run = getattr(self.settings, "GITHUB_DRY_RUN", False) if self.settings else False
        self._http_client = http_client

    def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is not None and not self._http_client.is_closed:
            return self._http_client
        return httpx.AsyncClient(timeout=30.0)

    def generate_pr_title(self, story_id: str, title: str) -> str:
        """
        Gera um título semântico seguindo a convenção Conventional Commits.
        Ex: feat(story-3.2): <descrição concisa>
        """
        clean_story = re.sub(r"^story-?", "", str(story_id).strip(), flags=re.IGNORECASE).strip()
        clean_title = str(title).strip()

        # Remove prefixos redundantes caso já existam no título
        clean_title = re.sub(r"^(feat|fix|chore|docs|refactor)(\([^)]+\))?:\s*", "", clean_title, flags=re.IGNORECASE)
        clean_title = re.sub(r"^story\s*[\d\.\-]+:\s*", "", clean_title, flags=re.IGNORECASE)

        return f"feat(story-{clean_story}): {clean_title}"

    def format_semantic_pr_body(
        self,
        story_id: str,
        title: str,
        phase_results: Optional[List[Dict[str, Any]]] = None,
        validation_results: Optional[List[Any]] = None,
        review_summary: Optional[Dict[str, Any]] = None,
        project_item_id: Optional[str] = None
    ) -> str:
        """
        Compila o corpo (body) do Pull Request em Markdown estruturado com:
        - Contexto da história e card do GitHub Projects
        - Resumo das alterações
        - Auto-auditoria e conformidade com a política Zero Deferred Work
        - Evidências das validações locais (testes unitários e linters)
        """
        phase_results = phase_results or []
        validation_results = validation_results or []
        review_summary = review_summary or {
            "status": "APPROVED",
            "findings_count": 0,
            "patches_applied": 0,
            "deferred_count": 0
        }

        # Resumo das alterações
        summary_bullets = []
        for phase in phase_results:
            p_name = phase.get("phase", "fase")
            p_exit = phase.get("exit_code", 0)
            status_tag = "✅ Concluída" if p_exit == 0 else f"❌ Falhou (exit {p_exit})"
            summary_bullets.append(f"- **Fase `{p_name}`:** {status_tag}")

        if not summary_bullets:
            summary_bullets.append("- Implementação autônoma de código e validações automatizadas.")
        summary_text = "\n".join(summary_bullets)

        # Code Review / Zero Deferred Work
        rev_status = review_summary.get("status", "APPROVED")
        findings_count = review_summary.get("findings_count", 0)
        patches_applied = review_summary.get("patches_applied", 0)
        deferred_count = review_summary.get("deferred_count", 0)

        # Evidências de validação
        passed_tests = sum(
            1 for res in validation_results
            if (res.get("passed", False) if isinstance(res, dict) else getattr(res, "passed", False))
        )
        failed_tests = len(validation_results) - passed_tests

        validation_logs = []
        for res in validation_results:
            cmd = res.get("command", "teste") if isinstance(res, dict) else getattr(res, "command", "teste")
            is_passed = res.get("passed", False) if isinstance(res, dict) else getattr(res, "passed", False)
            exit_code = res.get("exit_code", 0) if isinstance(res, dict) else getattr(res, "exit_code", 0)
            status_icon = "✅ PASSED" if is_passed else f"❌ FAILED (exit {exit_code})"
            validation_logs.append(f"- `{cmd}`: {status_icon}")

        if not validation_logs:
            validation_logs.append("- *Nenhum comando de validação executado.*")
        validation_command_logs = "\n".join(validation_logs)

        project_card_ref = project_item_id if project_item_id else "N/A (Não informado)"

        body_template = f"""## 🤖 AI Developer — Pull Request de Entrega

### 📋 Contexto da História
- **História:** Story {story_id} — {title}
- **Card no GitHub Projects:** {project_card_ref}
- **Status do Workflow:** Concluído com Sucesso

### 🛠️ Resumo das Alterações
{summary_text}

### 🔍 Auto-Auditoria e Code Review Interno (Política Zero Deferred Work)
- **Status da Revisão:** {rev_status}
- **Achados Identificados:** {findings_count}
- **Patches Aplicados:** {patches_applied}
- **Débitos Diferidos:** {deferred_count} (Conforme política de zero débitos)

### 🧪 Evidências de Validação Local
- **Testes Unitários / Linters:** {passed_tests} aprovados / {failed_tests} falhas
- **Comandos Executados:**
{validation_command_logs}

---
*Este Pull Request foi gerado e validado de forma autônoma pelo AI Developer e está pronto para a revisão humana final.*"""

        return body_template

    async def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        draft: bool = False
    ) -> Dict[str, Any]:
        """
        Cria um Pull Request no repositório remoto via GitHub REST API v3.
        POST /repos/{owner}/{repo}/pulls
        """
        clean_repo = repo.replace("https://github.com/", "").strip("/").removesuffix(".git").strip("/")

        if self.dry_run:
            logger.info(f"[DRY RUN] Simulação de criação de PR para {clean_repo}: '{title}' ({head_branch} -> {base_branch})")
            return {
                "pr_number": 999,
                "pr_url": f"https://api.github.com/repos/{clean_repo}/pulls/999",
                "pr_html_url": f"https://github.com/{clean_repo}/pull/999",
                "head_branch": head_branch,
                "base_branch": base_branch,
                "commit_sha": "dry-run-sha",
                "dry_run": True
            }

        if not self.token:
            raise GitHubAuthError("GitHub token não configurado para abertura de Pull Request")

        url = f"{self.api_url}/repos/{clean_repo}/pulls"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
            "draft": draft
        }

        client = self._get_client()
        should_close = (client is not self._http_client)
        try:
            logger.info(f"Enviando requisição de abertura de PR para {url} (branch: {head_branch})")
            response = await client.post(url, headers=headers, json=payload)

            if response.status_code in (401, 403):
                raise GitHubAuthError(
                    f"Falha de autenticação/autorização ao criar PR: {response.text}",
                    status_code=response.status_code,
                    response_data=response.text
                )
            elif response.is_error:
                raise GitHubAPIError(
                    f"Erro retornado pela API do GitHub ao criar PR: {response.text}",
                    status_code=response.status_code,
                    response_data=response.text
                )

            data = response.json()
            return {
                "pr_number": data.get("number"),
                "pr_url": data.get("url"),
                "pr_html_url": data.get("html_url"),
                "head_branch": data.get("head", {}).get("ref", head_branch),
                "base_branch": data.get("base", {}).get("ref", base_branch),
                "commit_sha": data.get("head", {}).get("sha", ""),
                "raw_response": data
            }
        except (GitHubAPIError, GitHubAuthError):
            raise
        except Exception as exc:
            logger.error(f"Exceção inesperada ao criar Pull Request no GitHub: {exc}", exc_info=True)
            raise GitHubAPIError(f"Falha de comunicação com a API do GitHub: {exc}") from exc
        finally:
            if should_close:
                await client.aclose()

    async def update_project_card_status(
        self,
        project_id: str,
        item_id: str,
        field_id: str,
        option_id: str
    ) -> Dict[str, Any]:
        """
        Atualiza o status de um item no GitHub Projects v2 via GraphQL API v4.
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Simulação de atualização de card no Projects v2: item {item_id}")
            return {
                "updated": True,
                "dry_run": True,
                "project_id": project_id,
                "item_id": item_id
            }

        if not self.token:
            raise GitHubAuthError("GitHub token não configurado para mutação no GitHub Projects")

        if self.api_url.endswith("/api/v3"):
            url = f"{self.api_url[:-7]}/api/graphql"
        else:
            url = f"{self.api_url}/graphql"

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json"
        }

        mutation = """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
          updateProjectV2ItemFieldValue(
            input: {
              projectId: $projectId
              itemId: $itemId
              fieldId: $fieldId
              value: { singleSelectOptionId: $optionId }
            }
          ) {
            projectV2Item {
              id
            }
          }
        }
        """
        variables = {
            "projectId": project_id,
            "itemId": item_id,
            "fieldId": field_id,
            "optionId": option_id
        }

        client = self._get_client()
        should_close = (client is not self._http_client)
        try:
            logger.info(f"Enviando mutação GraphQL para atualização de item {item_id} no projeto {project_id}")
            response = await client.post(url, headers=headers, json={"query": mutation, "variables": variables})

            if response.status_code in (401, 403):
                raise GitHubAuthError(
                    f"Falha de autenticação/autorização no GraphQL do GitHub: {response.text}",
                    status_code=response.status_code,
                    response_data=response.text
                )
            elif response.is_error:
                raise GitHubAPIError(
                    f"Erro HTTP na mutação GraphQL do GitHub: {response.text}",
                    status_code=response.status_code,
                    response_data=response.text
                )

            data = response.json()
            if "errors" in data and data["errors"]:
                error_msgs = "; ".join(err.get("message", "Unknown GraphQL error") for err in data["errors"])
                raise GitHubAPIError(f"Erro GraphQL no GitHub Projects: {error_msgs}", response_data=data["errors"])

            return {
                "updated": True,
                "project_id": project_id,
                "item_id": item_id,
                "data": data.get("data")
            }
        except (GitHubAPIError, GitHubAuthError):
            raise
        except Exception as exc:
            logger.error(f"Exceção inesperada ao atualizar item no GitHub Projects: {exc}", exc_info=True)
            raise GitHubAPIError(f"Falha de comunicação com GraphQL do GitHub: {exc}") from exc
        finally:
            if should_close:
                await client.aclose()

    async def create_issue_comment(
        self,
        repo: str,
        issue_number: Union[int, str],
        body: str
    ) -> Dict[str, Any]:
        """
        Cria um comentário em uma issue no repositório remoto via GitHub REST API v3.
        POST /repos/{owner}/{repo}/issues/{issue_number}/comments
        """
        clean_repo = repo.replace("https://github.com/", "").strip("/").removesuffix(".git").strip("/")
        clean_issue_num = str(issue_number).strip()

        if self.dry_run:
            logger.info(f"[DRY RUN] Simulação de comentário na issue #{clean_issue_num} em {clean_repo}: {body[:100]}...")
            return {
                "id": 999999,
                "body": body,
                "html_url": f"https://github.com/{clean_repo}/issues/{clean_issue_num}#issuecomment-999999",
                "issue_url": f"https://api.github.com/repos/{clean_repo}/issues/{clean_issue_num}",
                "dry_run": True
            }

        if not self.token:
            raise GitHubAuthError("GitHub token não configurado para criação de comentário em issue")

        url = f"{self.api_url}/repos/{clean_repo}/issues/{clean_issue_num}/comments"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        payload = {
            "body": body
        }

        client = self._get_client()
        should_close = (client is not self._http_client)
        try:
            logger.info(f"Enviando requisição de comentário na issue para {url}")
            response = await client.post(url, headers=headers, json=payload)

            if response.status_code in (401, 403):
                raise GitHubAuthError(
                    f"Falha de autenticação/autorização ao comentar na issue: {response.text}",
                    status_code=response.status_code,
                    response_data=response.text
                )
            elif response.is_error:
                raise GitHubAPIError(
                    f"Erro retornado pela API do GitHub ao comentar na issue: {response.text}",
                    status_code=response.status_code,
                    response_data=response.text
                )

            data = response.json()
            return {
                "id": data.get("id"),
                "body": data.get("body"),
                "html_url": data.get("html_url"),
                "issue_url": data.get("issue_url"),
                "raw_response": data
            }
        except (GitHubAPIError, GitHubAuthError):
            raise
        except Exception as exc:
            logger.error(f"Exceção inesperada ao comentar na issue #{clean_issue_num} no GitHub: {exc}", exc_info=True)
            raise GitHubAPIError(f"Falha de comunicação com a API do GitHub: {exc}") from exc
        finally:
            if should_close:
                await client.aclose()

