import asyncio
import logging
from typing import Optional, List
from executor.src.config import ExecutorSettings, settings as global_settings
from executor.src.sandbox import DockerSandboxManager
from persistence.src.repository import EventRepository, EventRecord

logger = logging.getLogger(__name__)


class ExecutorWorker:
    """
    Worker assíncrono de consumo e despache de jobs para containers efêmeros Docker.
    Consome eventos de status PENDING via claim_event (SKIP LOCKED) e orquestra o ciclo de vida.
    """

    def __init__(
        self,
        repo: EventRepository,
        sandbox_manager: Optional[DockerSandboxManager] = None,
        settings: Optional[ExecutorSettings] = None,
        event_types: Optional[List[str]] = None
    ):
        self.repo = repo
        self.settings = settings or global_settings
        self.sandbox_manager = sandbox_manager or DockerSandboxManager(settings=self.settings)
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
        """Processa um evento reivindicado executando o job no sandbox efêmero."""
        payload = event.payload if isinstance(event.payload, dict) else {}
        command = payload.get("command", "echo 'Nenhum comando especificado'")
        image = payload.get("image", self.settings.SANDBOX_IMAGE)
        env_vars = payload.get("env_vars", None)

        try:
            result = await asyncio.to_thread(
                self.sandbox_manager.execute_job,
                command=command,
                image=image,
                env_vars=env_vars
            )
            exit_code = result.get("exit_code", -1)
            logs = result.get("logs", "")
            container_id = result.get("container_id", "")

            if exit_code == 0:
                logger.info(f"Job do evento {event.event_id} concluído com sucesso.")
                await self.repo.complete_event(
                    event.event_id,
                    self.settings.WORKER_ID,
                    details={"exit_code": exit_code, "logs": logs, "container_id": container_id}
                )
            else:
                err_msg = f"Job encerrado com erro (exit code {exit_code}): {logs}"
                if len(err_msg) > 2000:
                    err_msg = err_msg[:2000] + "... [truncado]"
                logger.warning(f"Evento {event.event_id} falhou: {err_msg}")
                await self.repo.fail_event(
                    event.event_id,
                    self.settings.WORKER_ID,
                    error_message=err_msg
                )
        except Exception as e:
            err_msg = f"Falha na execução do sandbox Docker: {str(e)}"
            if len(err_msg) > 2000:
                err_msg = err_msg[:2000] + "... [truncado]"
            logger.error(f"Erro ao processar evento {event.event_id}: {err_msg}", exc_info=True)
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
