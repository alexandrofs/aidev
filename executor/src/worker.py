import asyncio
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

from executor.src.config import ExecutorSettings, settings as global_settings
from executor.src.sandbox import DockerSandboxManager
from executor.src.context_loader import ContextLoader
from executor.src.validation import ValidationPipeline
from executor.src.memory import AgentMemoryManager
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
    4. Persistência de memória hierárquica (PostgreSQL agent_memory + repositório .memlog.md)
    """

    def __init__(
        self,
        repo: EventRepository,
        sandbox_manager: Optional[DockerSandboxManager] = None,
        context_loader: Optional[ContextLoader] = None,
        validation_pipeline: Optional[ValidationPipeline] = None,
        memory_manager: Optional[AgentMemoryManager] = None,
        settings: Optional[ExecutorSettings] = None,
        event_types: Optional[List[str]] = None
    ):
        self.repo = repo
        self.settings = settings or global_settings
        self.sandbox_manager = sandbox_manager or DockerSandboxManager(settings=self.settings)
        self.context_loader = context_loader or ContextLoader(settings_override=self.settings)
        self.validation_pipeline = validation_pipeline or ValidationPipeline(sandbox_manager=self.sandbox_manager, settings=self.settings)
        self.memory_manager = memory_manager or AgentMemoryManager(repo=self.repo, settings=self.settings)
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

        raw_phases = payload.get("phases")
        if raw_phases and isinstance(raw_phases, list):
            phases = raw_phases
        else:
            phases = [payload.get("phase", "coding")]

        phase_results = []

        # 1 & 2. Execução das Fases no Sandbox Docker
        for phase in phases:
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
                    await self.repo.fail_event(
                        event.event_id,
                        self.settings.WORKER_ID,
                        error_message=err_msg
                    )
                    return
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
        story_id = payload.get("story_id", event.event_id)
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

            # Persistência Nível 2 (PostgreSQL agent_memory)
            await self.memory_manager.record_daily_summary(story_id=story_id, summary_data=summary_data)

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
            await self.repo.complete_event(
                event.event_id,
                self.settings.WORKER_ID,
                details={
                    "phases": phase_results,
                    "validation_results": [res.model_dump() for res in validation_results],
                    "exit_code": last_result.get("exit_code", 0),
                    "logs": last_result.get("logs", ""),
                    "container_id": last_result.get("container_id", "")
                }
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
            await self.memory_manager.record_daily_summary(story_id=story_id, summary_data=summary_data)

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
