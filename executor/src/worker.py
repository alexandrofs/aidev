import asyncio
import logging
import re
from typing import Optional, List, Dict, Any
from pathlib import Path

from executor.src.config import ExecutorSettings, settings as global_settings
from executor.src.sandbox import DockerSandboxManager
from executor.src.context_loader import ContextLoader
from executor.src.validation import ValidationPipeline
from executor.src.memory import AgentMemoryManager
from executor.src.github import GitHubClient, GitHubAPIError, GitHubAuthError
from executor.src.exceptions import ContextError
from persistence.src.repository import EventRepository, EventRecord

logger = logging.getLogger(__name__)


class ExecutorWorker:
    """
    Worker assíncrono de consumo e despache de jobs para containers efêmeros Docker.
    Consome eventos de status PENDING via claim_event (SKIP LOCKED) e orquestra o ciclo de vida:
    1. Injeção dinâmica de contexto
    2. Execução das fases no Sandbox Docker
    3. Pipeline de validação local pré-entrega (testes / linters)
    4. Geração semântica e abertura de Pull Request no GitHub
    5. Sincronização de status com GitHub Projects v2
    6. Persistência de memória hierárquica (PostgreSQL agent_memory + repositório .memlog.md)
    """

    def __init__(
        self,
        repo: EventRepository,
        sandbox_manager: Optional[DockerSandboxManager] = None,
        context_loader: Optional[ContextLoader] = None,
        validation_pipeline: Optional[ValidationPipeline] = None,
        memory_manager: Optional[AgentMemoryManager] = None,
        github_client: Optional[GitHubClient] = None,
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
        self.event_types = event_types or ["workflow.execution"]
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
                await asyncio.sleep(self.current_poll_interval)

    async def _process_event(self, event: EventRecord) -> None:
        """Processa um evento reivindicado executando fases, validação pré-entrega e atualização de memória."""
        payload = event.payload if isinstance(event.payload, dict) else {}
        command = payload.get("command", "echo 'Nenhum comando especificado'")
        image = payload.get("image", self.settings.SANDBOX_IMAGE)
        env_vars = payload.get("env_vars", None)
        story_id = payload.get("story_id", event.event_id)

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

        # 1 & 2. Execução das Fases no Sandbox Docker
        for phase in phases:
            if hasattr(self.repo, "add_audit_log"):
                try:
                    await self.repo.add_audit_log(
                        event_id=event.event_id,
                        action="WORKFLOW_PHASE_STARTED",
                        actor=self.settings.WORKER_ID,
                        details={"phase": phase, "story_id": story_id}
                    )
                except Exception as log_err:
                    logger.warning(f"Erro ao registrar audit_log WORKFLOW_PHASE_STARTED: {log_err}")

            context_bundle = None
            try:
                context_bundle = self.context_loader.build_context_bundle(phase=phase)
                logger.info(f"Pacote de contexto compilado com sucesso para a fase '{phase}' no evento {event.event_id}.")
            except ContextError as err:
                err_msg = f"Falha de injeção de contexto (fase '{phase}'): {err}"
                logger.error(err_msg)
                if hasattr(self.repo, "add_audit_log"):
                    try:
                        await self.repo.add_audit_log(
                            event_id=event.event_id,
                            action="CONTEXT_LOAD_FAILED",
                            actor=self.settings.WORKER_ID,
                            details={"error": str(err), "phase": phase}
                        )
                    except Exception as log_err:
                        logger.warning(f"Não foi possível registrar audit_log para falha de contexto: {log_err}")
                await self.repo.fail_event(
                    event.event_id,
                    self.settings.WORKER_ID,
                    error_message=err_msg
                )
                return

            try:
                result = await asyncio.to_thread(
                    self.sandbox_manager.execute_job,
                    command=command,
                    image=image,
                    env_vars=env_vars,
                    context_bundle=context_bundle
                )
                exit_code = result.get("exit_code", -1)
                logs = result.get("logs", "")
                container_id = result.get("container_id", "")

                phase_results.append({
                    "phase": phase,
                    "exit_code": exit_code,
                    "logs": logs,
                    "container_id": container_id
                })

                if exit_code != 0:
                    err_msg = f"Job da fase '{phase}' encerrado com erro (exit code {exit_code}): {logs}"
                    if len(err_msg) > 2000:
                        err_msg = err_msg[:2000] + "... [truncado]"
                    logger.warning(f"Evento {event.event_id} falhou na fase '{phase}': {err_msg}")

                    if phase == "review" and hasattr(self.repo, "add_audit_log"):
                        try:
                            await self.repo.add_audit_log(
                                event_id=event.event_id,
                                action="CODE_REVIEW_FAILED",
                                actor=self.settings.WORKER_ID,
                                details={"story_id": story_id, "exit_code": exit_code, "logs": logs[:500]}
                            )
                        except Exception as log_err:
                            logger.warning(f"Erro ao registrar audit_log CODE_REVIEW_FAILED: {log_err}")

                    await self.repo.fail_event(
                        event.event_id,
                        self.settings.WORKER_ID,
                        error_message=err_msg
                    )
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

                if phase == "review" and hasattr(self.repo, "add_audit_log"):
                    try:
                        await self.repo.add_audit_log(
                            event_id=event.event_id,
                            action="CODE_REVIEW_PASSED",
                            actor=self.settings.WORKER_ID,
                            details={"story_id": story_id, "review_summary": review_summary}
                        )
                    except Exception as log_err:
                        logger.warning(f"Erro ao registrar audit_log CODE_REVIEW_PASSED: {log_err}")

            except Exception as e:
                err_msg = f"Falha na execução do sandbox Docker na fase '{phase}': {str(e)}"
                if len(err_msg) > 2000:
                    err_msg = err_msg[:2000] + "... [truncado]"
                logger.error(f"Erro ao processar evento {event.event_id} na fase '{phase}': {err_msg}", exc_info=True)
                await self.repo.fail_event(
                    event.event_id,
                    self.settings.WORKER_ID,
                    error_message=err_msg
                )
                return

        # 3. Pipeline de Validação Local Pré-Entrega (Testes e Linters)
        validation_cmds = payload.get("validation_commands", getattr(self.settings, "VALIDATION_COMMANDS", ["pytest"]))

        logger.info(f"Executando pipeline de validação pré-entrega para evento {event.event_id} (story: {story_id})")
        try:
            validation_results = await asyncio.to_thread(
                self.validation_pipeline.run_validations,
                commands=validation_cmds,
                image=image,
                env_vars=env_vars
            )
        except Exception as val_exc:
            logger.error(f"Erro na execução do pipeline de validação: {val_exc}")
            # F2: lista vazia indica erro de infra (pipeline não executou), não falha de testes
            err_msg = f"Pipeline de validação falhou com exceção: {val_exc}"
            if len(err_msg) > 2000:
                err_msg = err_msg[:2000] + "... [truncado]"
            await self.repo.fail_event(
                event.event_id,
                self.settings.WORKER_ID,
                error_message=err_msg
            )
            return

        validation_passed = all(res.passed for res in validation_results)

        passed_count = sum(1 for res in validation_results if res.passed)
        failed_count = len(validation_results) - passed_count
        summary_data = {
            "title": payload.get("title") or payload.get("story_title") or f"Execução {event.event_id}",
            "status": "COMPLETED" if validation_passed else "VALIDATION_FAILED",
            "actions": [f"Execução das fases: {', '.join(phases)}", f"Validação local ({len(validation_cmds)} comandos)"],
            "test_results": {"passed": passed_count, "failed": failed_count},
            "decisions": f"Validação pré-entrega {'aprovada' if validation_passed else 'reprovada com falhas'}"
        }
        if "review" in phases:
            summary_data["review_summary"] = review_summary

        if validation_passed:
            # Audit log VALIDATION_PASSED
            if hasattr(self.repo, "add_audit_log"):
                try:
                    await self.repo.add_audit_log(
                        event_id=event.event_id,
                        action="VALIDATION_PASSED",
                        actor=self.settings.WORKER_ID,
                        details={"story_id": story_id, "commands": validation_cmds}
                    )
                except Exception as log_err:
                    logger.warning(f"Erro ao registrar audit_log VALIDATION_PASSED: {log_err}")

            # 4. Publicação de Branch e Abertura do Pull Request (Story 3.2)
            repo_name = payload.get("repository") or payload.get("repo") or getattr(self.settings, "GITHUB_REPOSITORY", None)
            is_dry_run = getattr(self.settings, "GITHUB_DRY_RUN", False)
            has_token = bool(getattr(self.settings, "GITHUB_TOKEN", None))
            pr_info = None

            if repo_name or is_dry_run:
                target_repo = repo_name or "local/repo"
                clean_story = re.sub(r"^story-?", "", str(story_id).strip(), flags=re.IGNORECASE).strip()
                head_branch = payload.get("head_branch") or payload.get("branch") or f"feature/story-{clean_story}"
                base_branch = payload.get("base_branch") or getattr(self.settings, "GITHUB_BASE_BRANCH", "main")
                title_text = payload.get("title") or payload.get("story_title") or f"Story {story_id}"
                project_item_id = payload.get("project_item_id") or payload.get("project_card_id")
                project_id = payload.get("project_id") or getattr(self.settings, "GITHUB_PROJECT_ID", None)
                project_field_id = payload.get("project_field_id")
                project_option_id = payload.get("project_option_id")

                if hasattr(self.repo, "add_audit_log"):
                    try:
                        await self.repo.add_audit_log(
                            event_id=event.event_id,
                            action="PR_CREATION_STARTED",
                            actor=self.settings.WORKER_ID,
                            details={
                                "story_id": story_id,
                                "repository": target_repo,
                                "head_branch": head_branch,
                                "base_branch": base_branch
                            }
                        )
                    except Exception as log_err:
                        logger.warning(f"Erro ao registrar audit_log PR_CREATION_STARTED: {log_err}")

                pr_title = self.github_client.generate_pr_title(story_id=story_id, title=title_text)
                pr_body = self.github_client.format_semantic_pr_body(
                    story_id=story_id,
                    title=title_text,
                    phase_results=phase_results,
                    validation_results=validation_results,
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
                                details={
                                    "story_id": story_id,
                                    "pr_number": pr_info.get("pr_number"),
                                    "pr_url": pr_info.get("pr_url"),
                                    "pr_html_url": pr_info.get("pr_html_url"),
                                    "head_branch": pr_info.get("head_branch"),
                                    "commit_sha": pr_info.get("commit_sha")
                                }
                            )
                        except Exception as log_err:
                            logger.warning(f"Erro ao registrar audit_log PR_CREATED: {log_err}")

                    # Sincronização do GitHub Projects v2 (AC: 3)
                    if project_item_id and project_id:
                        try:
                            await self.github_client.update_project_card_status(
                                project_id=project_id,
                                item_id=project_item_id,
                                field_id=project_field_id or "status",
                                option_id=project_option_id or "review"
                            )
                            if hasattr(self.repo, "add_audit_log"):
                                try:
                                    await self.repo.add_audit_log(
                                        event_id=event.event_id,
                                        action="PROJECTS_CARD_UPDATED",
                                        actor=self.settings.WORKER_ID,
                                        details={
                                            "project_id": project_id,
                                            "item_id": project_item_id,
                                            "story_id": story_id
                                        }
                                    )
                                except Exception as log_err:
                                    logger.warning(f"Erro ao registrar audit_log PROJECTS_CARD_UPDATED: {log_err}")
                        except Exception as proj_err:
                            logger.warning(f"Erro ao atualizar status do card no GitHub Projects v2: {proj_err}")

                except Exception as pr_err:
                    err_msg = f"Falha na abertura de Pull Request no GitHub: {pr_err}"
                    logger.error(err_msg, exc_info=True)
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
                    await self.repo.fail_event(
                        event.event_id,
                        self.settings.WORKER_ID,
                        error_message=err_msg
                    )
                    return

            if pr_info:
                summary_data["pr_url"] = pr_info.get("pr_html_url") or pr_info.get("pr_url")
                summary_data["pr_number"] = pr_info.get("pr_number")
                summary_data["pull_request_status"] = "OPEN"
                summary_data["head_branch"] = pr_info.get("head_branch")

            # Persistência Nível 2 (PostgreSQL agent_memory)
            # F5: event_id passado para ativar UPSERT idempontente no repositório
            await self.memory_manager.record_daily_summary(
                story_id=story_id,
                summary_data=summary_data,
                event_id=event.event_id
            )

            # Persistência Nível 3 (.memlog.md no repositório)
            # F1: executado em thread para não bloquear o event loop com I/O síncrono
            workspace_rel = payload.get("workspace_path", ".")
            workspace_path = self.settings.resolve_path(workspace_rel)
            try:
                await asyncio.to_thread(
                    self.memory_manager.sync_memlog_file,
                    workspace_path=workspace_path,
                    story_id=story_id,
                    summary_data=summary_data
                )
            except Exception as mem_err:
                logger.warning(f"Erro ao sincronizar .memlog.md: {mem_err}")

            # Conclusão do Evento
            last_result = phase_results[-1] if phase_results else {}
            validation_details = [
                (res.model_dump() if hasattr(res, "model_dump") else (dict(res) if isinstance(res, dict) else vars(res)))
                for res in validation_results
            ]
            details = {
                "phases": phase_results,
                "validation_results": validation_details,
                "exit_code": last_result.get("exit_code", 0),
                "logs": last_result.get("logs", ""),
                "container_id": last_result.get("container_id", ""),
                "ready_for_pr": True
            }
            if "review" in phases:
                details["review_summary"] = review_summary
            if pr_info:
                details["pr_number"] = pr_info.get("pr_number")
                details["pr_url"] = pr_info.get("pr_html_url") or pr_info.get("pr_url")
                details["head_branch"] = pr_info.get("head_branch")
                details["base_branch"] = pr_info.get("base_branch")
                details["commit_sha"] = pr_info.get("commit_sha")

            await self.repo.complete_event(
                event.event_id,
                self.settings.WORKER_ID,
                details=details
            )
        else:
            # Audit log VALIDATION_FAILED
            failed_cmd = next((res.command for res in validation_results if not res.passed), "unknown")
            failed_err = next((res.stderr or res.stdout for res in validation_results if not res.passed), "Falha no teste/linter")

            if hasattr(self.repo, "add_audit_log"):
                try:
                    await self.repo.add_audit_log(
                        event_id=event.event_id,
                        action="VALIDATION_FAILED",
                        actor=self.settings.WORKER_ID,
                        details={"story_id": story_id, "failed_command": failed_cmd, "error": failed_err}
                    )
                except Exception as log_err:
                    logger.warning(f"Erro ao registrar audit_log VALIDATION_FAILED: {log_err}")

            # Persistência Nível 2 do registro de erro
            # F5: event_id passado para ativar UPSERT idempontente no repositório
            await self.memory_manager.record_daily_summary(
                story_id=story_id,
                summary_data=summary_data,
                event_id=event.event_id
            )

            # F4: Nível 3 (.memlog.md) também atualizado em caso de falha, mantendo consistência com o DB
            workspace_rel = payload.get("workspace_path", ".")
            workspace_path = self.settings.resolve_path(workspace_rel)
            try:
                await asyncio.to_thread(
                    self.memory_manager.sync_memlog_file,
                    workspace_path=workspace_path,
                    story_id=story_id,
                    summary_data=summary_data
                )
            except Exception as mem_err:
                logger.warning(f"Erro ao sincronizar .memlog.md em falha de validação: {mem_err}")

            err_msg = f"Validação pré-entrega falhou no comando '{failed_cmd}': {failed_err}"
            if len(err_msg) > 2000:
                err_msg = err_msg[:2000] + "... [truncado]"
            logger.warning(f"Evento {event.event_id} reprovado no pipeline de validação: {err_msg}")

            await self.repo.fail_event(
                event.event_id,
                self.settings.WORKER_ID,
                error_message=err_msg
            )

    def stop(self) -> None:
        """Solicita o encerramento gracioso do worker."""
        logger.info(f"Encerrando worker {self.settings.WORKER_ID} graciosamente...")
        self.running = False
        if self._sleep_task and not self._sleep_task.done():
            self._sleep_task.cancel()
