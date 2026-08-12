import os
import shutil
import logging
import tempfile
from typing import Dict, Optional, Generator, Any
from contextlib import contextmanager
import docker
from executor.src.config import ExecutorSettings, settings as global_settings

logger = logging.getLogger(__name__)


class DockerSandboxManager:
    """
    Orquestrador de sandbox Docker efêmero.
    Garante a criação, isolamento, montagem de diretório efêmero e teardown completo (zero leakage).
    """

    def __init__(
        self,
        docker_client: Optional[docker.DockerClient] = None,
        settings: Optional[ExecutorSettings] = None
    ):
        self._client = docker_client
        self.settings = settings or global_settings

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    @contextmanager
    def run_sandbox(
        self,
        image: Optional[str] = None,
        command: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        working_dir: str = "/workspace"
    ) -> Generator[docker.models.containers.Container, None, None]:
        """
        Gerenciador de contexto que cria e executa um container Docker efêmero com volume temporário.
        Ao sair do bloco context, limpa obrigatoriamente o container e os arquivos temporários do host.
        """
        temp_dir = tempfile.mkdtemp(prefix="aidev_sandbox_")
        try:
            os.chmod(temp_dir, 0o700)
        except Exception as e:
            logger.warning(f"Não foi possível aplicar permissão restrita em {temp_dir}: {e}")

        target_image = image or self.settings.SANDBOX_IMAGE
        container = None

        try:
            volumes = {
                temp_dir: {"bind": working_dir, "mode": "rw"}
            }
            logger.info(f"Criando container sandbox efêmero com imagem {target_image}")
            container = self.client.containers.run(
                image=target_image,
                command=command,
                environment=env_vars or {},
                volumes=volumes,
                working_dir=working_dir,
                detach=True,
                auto_remove=False  # Gerenciado no cleanup para recuperação de logs e status
            )
            yield container
        finally:
            self.cleanup_sandbox(container, temp_dir)

    def cleanup_sandbox(self, container: Optional[Any] = None, temp_dir: Optional[str] = None) -> None:
        """
        Teardown completo do container (stop + remove) e destruição de diretórios efêmeros.
        """
        if container:
            try:
                logger.info(f"Encerrando container sandbox {getattr(container, 'id', 'desconhecido')}")
                container.stop(timeout=5)
            except Exception as e:
                logger.warning(f"Erro ao interromper container {getattr(container, 'id', 'desconhecido')}: {e}")

            try:
                logger.info(f"Removendo container sandbox {getattr(container, 'id', 'desconhecido')}")
                container.remove(v=True, force=True)
            except Exception as e:
                logger.warning(f"Erro ao remover container {getattr(container, 'id', 'desconhecido')}: {e}")

        if temp_dir and os.path.exists(temp_dir):
            try:
                logger.info(f"Limpando diretório temporário efêmero: {temp_dir}")
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Erro ao deletar diretório temporário {temp_dir}: {e}")

    def execute_job(
        self,
        command: str,
        image: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        max_log_bytes: int = 65536
    ) -> Dict[str, Any]:
        """
        Executa um comando síncrono dentro do sandbox efêmero, aguarda conclusão, captura logs e faz teardown.
        """
        timeout_val = timeout or self.settings.CONTAINER_TIMEOUT
        with self.run_sandbox(image=image, command=command, env_vars=env_vars) as container:
            exit_code = -1
            try:
                res = container.wait(timeout=timeout_val)
                exit_code = res.get("StatusCode", -1) if isinstance(res, dict) else res
            except Exception as e:
                logger.error(f"Exceção ao aguardar término do container sandbox (timeout={timeout_val}s): {e}")

            try:
                raw_logs = container.logs(stdout=True, stderr=True)
                if isinstance(raw_logs, bytes):
                    logs = raw_logs.decode("utf-8", errors="replace")
                else:
                    logs = str(raw_logs or "")
            except Exception as e:
                logger.warning(f"Erro ao capturar logs do container: {e}")
                logs = f"[Erro ao obter logs: {e}]"

            if len(logs) > max_log_bytes:
                logs = logs[:max_log_bytes] + "\n... [logs truncados pelo executor devido ao limite de tamanho]"

            return {
                "exit_code": exit_code,
                "logs": logs,
                "container_id": getattr(container, "id", None)
            }
