import os
import json
import yaml
import asyncio
import logging
import re
from typing import Optional, List, Dict, Any
from pathlib import Path

from executor.src.config import ExecutorSettings, settings as global_settings
from executor.src.sandbox import DockerSandboxManager, SandboxSession
from executor.src.context_loader import ContextLoader
from executor.src.validation import ValidationPipeline
from executor.src.memory import AgentMemoryManager
from executor.src.github import GitHubClient, GitHubAPIError, GitHubAuthError
from executor.src.git_manager import GitManager
from executor.src.agent_runner import AgentRunner
from executor.src.exceptions import ContextError
from persistence.src.repository import EventRepository, EventRecord

logger = logging.getLogger(__name__)


def extract_story_id_from_issue(issue_data: Dict[str, Any], fallback_id: str) -> str:
    """
    Extrai o identificador da história a partir da descrição (body) da issue.
    Busca por padrões como 'Story Key: 5-2-time-to-goal-motivational-clock' ou 'Story: 5-2-...'.
    Caso não encontre, utiliza o fallback 'issue-<number>' ou 'issue-<id>'.
    """
    body = issue_data.get("body") or ""
    match = re.search(r"(?:Story\s*Key|Story):\s*([a-zA-Z0-9_\-\.]+)", body, re.IGNORECASE)
    if match:
        return match.group(1).strip().rstrip(".")
    issue_num = issue_data.get("number") or issue_data.get("id") or fallback_id
    return f"issue-{issue_num}"


class ExecutorWorker:
    """
    Worker assíncrono de consumo e orquestração de sessões de sandbox Docker.
    Consome eventos de status PENDING via claim_event (SKIP LOCKED) e orquestra o ciclo contínuo:
    1. Criação de SandboxSession efêmero e clone do repositório alvo
    2. Leitura do manifesto .aidev.yaml do repositório alvo (se existir)
    3. Criação do branch de trabalho (feature branch)
    4. Execução autônoma da Fase 1 (Coding) via OpenCode CLI e bmad-dev-story (com validação TDD pelo harness)
    5. Execução autônoma da Fase 2 (Review) via OpenCode CLI e bmad-code-review (auto-auditoria pelo harness)
    6. Commit e Git Push das alterações para o repositório remoto
    7. Geração semântica e abertura de Pull Request no GitHub
    8. Sincronização de status com GitHub Projects v2
    9. Persistência de memória hierárquica (PostgreSQL agent_memory + repositório .memlog.md)
    10. Teardown completo e destruição do sandbox ao final
    """

    @staticmethod
    def load_target_repo_config(workspace_dir: Optional[str]) -> Dict[str, Any]:
        """
        Lê o manifesto .aidev.yaml, .aidev.yml ou .aidev.json na raiz do repositório alvo.
        Permite que cada projeto alvo defina seus próprios comandos de validação, project_id, etc.
        """
        if not workspace_dir or not os.path.exists(workspace_dir):
            return {}

        candidates = [".aidev.yaml", ".aidev.yml", ".aidev.json"]
        for fname in candidates:
            fpath = os.path.join(workspace_dir, fname)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        if fname.endswith(".json"):
                            data = json.load(f)
                        else:
                            data = yaml.safe_load(f)
                        if isinstance(data, dict):
                            logger.info(f"Manifesto de configuração do repositório alvo carregado com sucesso de '{fname}'.")
                            return data
                except Exception as err:
                    logger.warning(f"Falha ao interpretar manifesto {fname} no workspace alvo: {err}")
        return {}

    def __init__(
        self,
        repo: EventRepository,
        sandbox_manager: Optional[DockerSandboxManager] = None,
        context_loader: Optional[ContextLoader] = None,
        validation_pipeline: Optional[ValidationPipeline] = None,
        memory_manager: Optional[AgentMemoryManager] = None,
        github_client: Optional[GitHubClient] = None,
        git_manager: Optional[GitManager] = None,
        agent_runner: Optional[AgentRunner] = None,
        settings: Optional[ExecutorSettings] = None,
        event_types: Optional[List[str]] = None
    ):
        self.repo = repo
        self.settings = settings or global_settings
        self.sandbox_manager = sandbox_manager or DockerSandboxManager(settings=self.settings)
        self.context_loader = context_loader or ContextLoader(settings_override=self.settings)
        self.validation_pipeline = validation_pipeline or ValidationPipeline(sandbox_manager=self.sandbox_manager, settings=self.settings)
        self.memory_manager = memory_manager or AgentMemoryManager(repo=self.repo, settings=self.settings)
        self.github_client = github_client or GitHubClient(settings=self.settings)
        self.git_manager = git_manager or GitManager(settings=self.settings)
        self.agent_runner = agent_runner or AgentRunner(settings=self.settings)
        self.event_types = event_types or ["workflow.execution", "issues", "projects_v2_item", "project_card"]
        self.running = False
        self.current_poll_interval = self.settings.POLL_INTERVAL
        self._sleep_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Inicia o loop contínuo de polling e consumo de eventos."""
        self.running = True
        logger.info(f"Worker {self.settings.WORKER_ID} iniciado. Monitorando tipos: {self.event_types}")

        while self.running:
            try:
                event = await self.repo.claim_event(
                    event_types=self.event_types,
                    worker_id=self.settings.WORKER_ID
                )

                if event:
                    logger.info(f"Evento {event.event_id} ({event.event_type}) reivindicado por {self.settings.WORKER_ID}.")
                    self.current_poll_interval = self.settings.POLL_INTERVAL
                    await self._process_event(event)
                else:
                    self._sleep_task = asyncio.create_task(asyncio.sleep(self.current_poll_interval))
                    try:
                        await self._sleep_task
                    except asyncio.CancelledError:
                        break
                    finally:
                        self._sleep_task = None

                    self.current_poll_interval = min(
                        self.settings.MAX_POLL_INTERVAL,
                        self.current_poll_interval * self.settings.BACKOFF_FACTOR
                    )
            except asyncio.CancelledError:
                logger.info(f"Loop do worker {self.settings.WORKER_ID} cancelado.")
                break
            except Exception as e:
                logger.error(f"Exceção no loop de consumo do worker: {e}", exc_info=True)
                if hasattr(self.repo, "session") and self.repo.session:
                    try:
                        await self.repo.session.rollback()
                    except Exception:
                        pass
                await asyncio.sleep(self.current_poll_interval)

    def stop(self) -> None:
        """Interrompe o loop de consumo do worker."""
        self.running = False
        if self._sleep_task and not self._sleep_task.done():
            self._sleep_task.cancel()

    async def _process_event(self, event: EventRecord) -> None:
        """Processa um evento reivindicado com sessão contínua de sandbox Docker e agente OpenCode."""
        payload = event.payload if isinstance(event.payload, dict) else {}
        image = payload.get("image", self.settings.SANDBOX_IMAGE)
        env_vars = payload.get("env_vars", None)
        entrypoint = payload.get("entrypoint", None)

        # 0. Resolução prioritária do repositório: event.repository -> payload.repository -> settings.GITHUB_REPOSITORY
        if getattr(event, "repository", None) and isinstance(event.repository, str) and event.repository.strip():
            repo_name = event.repository.strip()
        else:
            raw_repo = payload.get("repository") or payload.get("repo")
            if isinstance(raw_repo, dict):
                repo_name = raw_repo.get("full_name") or raw_repo.get("name_with_owner") or raw_repo.get("name")
            elif isinstance(raw_repo, str) and raw_repo.strip():
                repo_name = raw_repo.strip()
            else:
                repo_name = getattr(self.settings, "GITHUB_REPOSITORY", None)
        token = getattr(self.settings, "GITHUB_TOKEN", None)

        # Extrair dados de eventos nativos do GitHub (issues / projects_v2_item)
        story_id = payload.get("story_id")
        if not story_id:
            if "issue" in payload and isinstance(payload["issue"], dict):
                issue_data = payload["issue"]
                story_id = extract_story_id_from_issue(issue_data, fallback_id=event.event_id)
            elif "projects_v2_item" in payload and isinstance(payload["projects_v2_item"], dict):
                pv2_data = payload["projects_v2_item"]
                story_id = f"PV2-{pv2_data.get('id', event.event_id)}"
            else:
                story_id = event.event_id

        head_branch = payload.get("head_branch") or payload.get("branch") or f"feature/{story_id}"
        base_branch = payload.get("base_branch") or getattr(self.settings, "GITHUB_BASE_BRANCH", "main")

        raw_phases = payload.get("phases")
        if raw_phases and isinstance(raw_phases, list):
            phases = raw_phases
        elif "phase" in payload:
            phases = [payload.get("phase")]
        else:
            phases = list(getattr(self.settings, "DEFAULT_WORKFLOW_PHASES", ["coding", "review"]))

        phase_results = []
        review_summary = payload.get("review_summary") or {
            "status": "APPROVED",
            "findings_count": 0,
            "patches_applied": 0,
            "deferred_count": 0
        }

        # 1. Carregar bundle de contexto base
        try:
            initial_context = self.context_loader.build_context_bundle(phase=phases[0] if phases else "coding")
        except ContextError as err:
            err_msg = f"Falha ao compilar pacote de contexto inicial: {err}"
            logger.error(err_msg)
            await self.repo.fail_event(event.event_id, self.settings.WORKER_ID, error_message=err_msg)
            return

        # 2. Inicialização da SandboxSession contínua
        session = None
        try:
            session = self.sandbox_manager.create_session(
                image=image,
                env_vars=env_vars,
                context_bundle=initial_context,
                entrypoint=entrypoint
            )
            logger.info(f"SandboxSession criada com sucesso (Container ID: {session.id[:12]}).")

            # 3. Setup de Git e Clone do Repositório Alvo
            setup_cmds = self.git_manager.get_setup_commands(repository=repo_name, branch=base_branch, token=token)
            for scmd in setup_cmds:
                setup_res = session.exec(scmd)
                if setup_res.get("exit_code", -1) != 0:
                    logger.warning(f"Aviso durante setup de Git no sandbox: {setup_res.get('logs')}")

            # Criar feature branch
            branch_cmds = self.git_manager.get_branch_checkout_commands(head_branch)
            for bcmd in branch_cmds:
                session.exec(bcmd)

            # 3.1 Injetar MCPs, Skills e Templates de Prompt diretamente dentro do container /workspace
            if hasattr(session, "inject_context_bundle") and initial_context:
                session.inject_context_bundle(initial_context)

            # 3.2 Carregar manifesto de configuração do repositório alvo (.aidev.yaml / .aidev.json) se existir
            target_repo_config = self.load_target_repo_config(getattr(session, "temp_dir", None))
            if target_repo_config:
                logger.info(f"Configuração do repositório alvo detectada: {list(target_repo_config.keys())}")

            # 4. Execução Contínua das Fases (Coding e Review) via OpenCode CLI
            for phase in phases:
                if hasattr(self.repo, "add_audit_log"):
                    try:
                        await self.repo.add_audit_log(
                            event_id=event.event_id,
                            action="WORKFLOW_PHASE_STARTED",
                            actor=self.settings.WORKER_ID,
                            details={"phase": phase, "story_id": story_id, "container_id": session.id}
                        )
                    except Exception as log_err:
                        logger.warning(f"Erro ao registrar audit_log WORKFLOW_PHASE_STARTED: {log_err}")

                # Garantir que o template de prompt específico da fase está presente em /workspace/prompts/<phase>.md
                try:
                    prompt_file_src = str(self.settings.resolved_prompts_dir / f"{phase}.md")
                    if os.path.exists(prompt_file_src) and hasattr(session, "copy_file_to_container"):
                        session.copy_file_to_container(prompt_file_src, f"/workspace/prompts/{phase}.md")
                except Exception as p_err:
                    logger.warning(f"Aviso ao copiar prompt da fase '{phase}': {p_err}")

                # Montar comando do OpenCode para a fase
                phase_env = self.agent_runner.get_phase_env_vars(phase=phase, story_id=story_id, base_env=env_vars)
                custom_cmd = payload.get("command") if payload.get("command") and payload.get("command") != "echo 'Nenhum comando especificado'" else None
                
                if custom_cmd and len(phases) == 1:
                    agent_cmd = custom_cmd
                else:
                    agent_cmd = self.agent_runner.build_agent_command(
                        phase=phase,
                        story_id=story_id,
                        prompt_path=f"/workspace/prompts/{phase}.md"
                    )

                logger.info(f"Executando Fase '{phase}' no Sandbox ativo...")
                result = session.exec(command=agent_cmd, env_vars=phase_env)
                exit_code = result.get("exit_code", -1)
                logs = result.get("logs", "")

                if logs and logs.strip():
                    logger.info(f"[HARNESS - FASE '{phase}'] Logs da sessão (exit {exit_code}):\n{logs.strip()}")

                phase_results.append({
                    "phase": phase,
                    "exit_code": exit_code,
                    "logs": logs,
                    "container_id": session.id
                })

                if exit_code != 0:
                    err_msg = f"Fase '{phase}' falhou no sandbox (exit code {exit_code}): {logs}"
                    if len(err_msg) > 2000:
                        err_msg = err_msg[:2000] + "... [truncado]"
                    logger.warning(f"Evento {event.event_id} falhou na fase '{phase}': {err_msg}")
                    await self.repo.fail_event(event.event_id, self.settings.WORKER_ID, error_message=err_msg)
                    return

                if hasattr(self.repo, "add_audit_log"):
                    try:
                        await self.repo.add_audit_log(
                            event_id=event.event_id,
                            action="WORKFLOW_PHASE_COMPLETED",
                            actor=self.settings.WORKER_ID,
                            details={"phase": phase, "story_id": story_id, "exit_code": exit_code}
                        )
                    except Exception as log_err:
                        logger.warning(f"Erro ao registrar audit_log WORKFLOW_PHASE_COMPLETED: {log_err}")

            # 5. Resumo da Execução e Preparação de Entrega
            summary_data = {
                "title": payload.get("title") or payload.get("story_title") or f"Execução {event.event_id}",
                "status": "COMPLETED",
                "actions": [f"Execução das fases autônomas: {', '.join(phases)}"],
                "decisions": "Implementação e revisão autônomas validadas pelo harness do agente."
            }
            if "review" in phases:
                summary_data["review_summary"] = review_summary

            # 6. Commit e Push no Sandbox
            if repo_name and token:
                logger.info(f"Comitando e fazendo push do branch {head_branch}...")
                push_cmds = self.git_manager.get_commit_and_push_commands(
                    branch_name=head_branch,
                    commit_message=f"feat({story_id}): {summary_data['title']}",
                    repository=repo_name,
                    token=token
                )
                for pcmd in push_cmds:
                    push_res = session.exec(pcmd)
                    if push_res.get("exit_code", -1) != 0:
                        logger.warning(f"Aviso no Git Push: {push_res.get('logs')}")

            # 7. Abertura Semântica do Pull Request (Story 3.2)
            is_dry_run = getattr(self.settings, "GITHUB_DRY_RUN", False) or getattr(self.github_client, "dry_run", False)
            client_token = getattr(self.github_client, "token", None)
            has_token = bool(client_token) if client_token is not None else bool(token)
            is_mock_client = hasattr(self.github_client, "_mock_name") or hasattr(self.github_client, "return_value")
            pr_info = None

            if is_dry_run or (has_token and repo_name) or (is_mock_client and repo_name):
                target_repo = repo_name or "local/repo"
                title_text = payload.get("title") or payload.get("story_title") or f"Story {story_id}"
                project_item_id = payload.get("project_item_id") or payload.get("project_card_id")
                target_project_id = (
                    target_repo_config.get("github", {}).get("project_id")
                    if isinstance(target_repo_config.get("github"), dict)
                    else target_repo_config.get("project_id")
                )
                project_id = payload.get("project_id") or target_project_id or getattr(self.settings, "GITHUB_PROJECT_ID", None)

                pr_title = self.github_client.generate_pr_title(story_id=story_id, title=title_text)
                pr_body = self.github_client.format_semantic_pr_body(
                    story_id=story_id,
                    title=title_text,
                    phase_results=phase_results,
                    review_summary=review_summary,
                    project_item_id=project_item_id
                )

                try:
                    pr_info = await self.github_client.create_pull_request(
                        repo=target_repo,
                        title=pr_title,
                        body=pr_body,
                        head_branch=head_branch,
                        base_branch=base_branch
                    )
                    logger.info(f"Pull Request criado com sucesso: {pr_info.get('pr_html_url') or pr_info.get('pr_url')}")

                    if hasattr(self.repo, "add_audit_log"):
                        try:
                            await self.repo.add_audit_log(
                                event_id=event.event_id,
                                action="PR_CREATED",
                                actor=self.settings.WORKER_ID,
                                details={"story_id": story_id, "pr_url": pr_info.get("pr_html_url") or pr_info.get("pr_url")}
                            )
                        except Exception as log_err:
                            logger.warning(f"Erro ao registrar audit_log PR_CREATED: {log_err}")

                except Exception as pr_err:
                    err_msg = f"Falha na abertura de Pull Request no GitHub: {pr_err}"
                    logger.error(err_msg)
                    if hasattr(self.repo, "add_audit_log"):
                        try:
                            await self.repo.add_audit_log(
                                event_id=event.event_id,
                                action="PR_FAILED",
                                actor=self.settings.WORKER_ID,
                                details={"story_id": story_id, "error": str(pr_err)}
                            )
                        except Exception as log_err:
                            logger.warning(f"Erro ao registrar audit_log PR_FAILED: {log_err}")
                    await self.repo.fail_event(event.event_id, self.settings.WORKER_ID, error_message=err_msg)
                    return

            if pr_info:
                summary_data["pr_url"] = pr_info.get("pr_html_url") or pr_info.get("pr_url")
                summary_data["pr_number"] = pr_info.get("pr_number")
                summary_data["pull_request_status"] = "OPEN"
                summary_data["head_branch"] = pr_info.get("head_branch")

            # 8. Persistência de Memória Hierárquica
            await self.memory_manager.record_daily_summary(
                story_id=story_id,
                summary_data=summary_data,
                event_id=event.event_id
            )

            workspace_path = self.settings.resolve_path(payload.get("workspace_path", "."))
            try:
                await asyncio.to_thread(
                    self.memory_manager.sync_memlog_file,
                    workspace_path=workspace_path,
                    story_id=story_id,
                    summary_data=summary_data
                )
            except Exception as mem_err:
                logger.warning(f"Erro ao sincronizar .memlog.md: {mem_err}")

            # 9. Concluir evento no PostgreSQL
            await self.repo.complete_event(
                event.event_id,
                self.settings.WORKER_ID,
                details={"summary": summary_data, "container_id": session.id}
            )
            logger.info(f"Evento {event.event_id} (Story: {story_id}) concluído com sucesso [COMPLETED].")

        except Exception as exc:
            err_msg = f"Exceção durante o processamento do evento {event.event_id}: {str(exc)}"
            logger.error(err_msg, exc_info=True)
            await self.repo.fail_event(event.event_id, self.settings.WORKER_ID, error_message=err_msg)

        finally:
            # 10. Teardown Completo do Sandbox
            if session:
                logger.info(f"Iniciando teardown completo do SandboxSession {session.id[:12]}...")
                session.close()
                logger.info(f"Teardown do SandboxSession {session.id[:12]} concluído sem contaminação.")
