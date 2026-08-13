import os
import json
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
        working_dir: str = "/workspace",
        context_bundle: Optional[Dict[str, Any]] = None
    ) -> Generator[docker.models.containers.Container, None, None]:
        """
        Gerenciador de contexto que cria e executa um container Docker efêmero com volume temporário.
        Injeta arquivos de contexto (MCPs, Skills, Prompts) no volume montado quando fornecido.
        Ao sair do bloco context, limpa obrigatoriamente o container e os arquivos temporários do host.
        """
        temp_dir = tempfile.mkdtemp(prefix="aidev_sandbox_")
        try:
            os.chmod(temp_dir, 0o700)
        except Exception as e:
            logger.warning(f"Não foi possível aplicar permissão restrita em {temp_dir}: {e}")

        final_env = dict(env_vars or {})

        if context_bundle:
            # 1. Injetar MCP Config
            if "mcp_config" in context_bundle and context_bundle["mcp_config"]:
                mcp_file = os.path.join(temp_dir, "mcp_config.json")
                with open(mcp_file, "w", encoding="utf-8") as f:
                    json.dump(context_bundle["mcp_config"], f, indent=2)
                final_env["MCP_CONFIG_PATH"] = f"{working_dir}/mcp_config.json"

            # 2. Injetar Skills
            if "skills" in context_bundle and context_bundle["skills"]:
                skills_base = os.path.join(temp_dir, ".agents", "skills")
                os.makedirs(skills_base, exist_ok=True)
                for s_name, s_data in context_bundle["skills"].items():
                    s_dir = os.path.join(skills_base, s_name)
                    os.makedirs(s_dir, exist_ok=True)
                    s_file = os.path.join(s_dir, "SKILL.md")
                    content = s_data.get("content", "") if isinstance(s_data, dict) else str(s_data)
                    with open(s_file, "w", encoding="utf-8") as f:
                        f.write(content)
                final_env["SKILLS_DIR"] = f"{working_dir}/.agents/skills"

            # 3. Injetar Prompts
            prompts_dict = dict(context_bundle.get("prompts") or {})
            if "prompt_template" in context_bundle and context_bundle.get("phase"):
                phase_name = context_bundle["phase"]
                prompts_dict[phase_name] = context_bundle["prompt_template"]

            if prompts_dict:
                prompts_base = os.path.join(temp_dir, "prompts")
                os.makedirs(prompts_base, exist_ok=True)
                for p_name, p_content in prompts_dict.items():
                    fname = p_name if p_name.endswith(".md") else f"{p_name}.md"
                    p_file = os.path.join(prompts_base, fname)
                    with open(p_file, "w", encoding="utf-8") as f:
                        f.write(p_content)
                final_env["PROMPTS_DIR"] = f"{working_dir}/prompts"

            if "phase" in context_bundle:
                final_env["WORKFLOW_PHASE"] = context_bundle["phase"]

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
                environment=final_env,
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
        max_log_bytes: int = 65536,
        context_bundle: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executa um comando síncrono dentro do sandbox efêmero, aguarda conclusão, captura logs e faz teardown.
        """
        timeout_val = timeout or self.settings.CONTAINER_TIMEOUT
        with self.run_sandbox(image=image, command=command, env_vars=env_vars, context_bundle=context_bundle) as container:
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
