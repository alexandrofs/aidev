import os
import json
import shutil
import logging
import tempfile
from typing import Dict, Optional, Generator, Any, List
from contextlib import contextmanager
import docker
from executor.src.config import ExecutorSettings, settings as global_settings

logger = logging.getLogger(__name__)


class SandboxSession:
    """
    Sessão contínua de Sandbox Docker efêmero.
    Mantém o container e o volume temporário ativos durante todo o ciclo de vida da história,
    permitindo múltiplos comandos sequenciais (git clone, coding, review, validação e git push)
    sem perda de estado ou re-instanciação de ambiente.
    """

    def __init__(
        self,
        container: Any,
        temp_dir: str,
        working_dir: str = "/workspace",
        manager: Optional["DockerSandboxManager"] = None
    ):
        self.container = container
        self.temp_dir = temp_dir
        self.working_dir = working_dir
        self.manager = manager
        self.closed = False

    @property
    def id(self) -> str:
        return getattr(self.container, "id", "unknown")

    def exec(
        self,
        command: str,
        env_vars: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        max_log_bytes: int = 65536
    ) -> Dict[str, Any]:
        """
        Executa um comando dentro do container ativo via exec_run e captura a saída.
        """
        if self.closed:
            raise RuntimeError("Tentativa de executar comando em SandboxSession já encerrada.")

        logger.info(f"Executando no sandbox [{self.id[:12]}]: {command[:120]}...")
        cmd_wrapper = ["/bin/sh", "-c", command]

        try:
            if hasattr(self.container, "exec_run"):
                exec_res = self.container.exec_run(
                    cmd=cmd_wrapper,
                    environment=env_vars,
                    workdir=self.working_dir,
                    stdout=True,
                    stderr=True,
                    demux=False
                )
                exit_code = getattr(exec_res, "exit_code", 0)
                output = getattr(exec_res, "output", b"")
                if isinstance(output, bytes):
                    logs = output.decode("utf-8", errors="replace")
                else:
                    logs = str(output or "")
            else:
                exit_code = 0
                logs = "Command executed in mock container"
        except Exception as e:
            logger.error(f"Erro na execução do comando no sandbox: {e}")
            exit_code = -1
            logs = f"[Erro de execução no container: {e}]"

        if len(logs) > max_log_bytes:
            logs = logs[:max_log_bytes] + "\n... [logs truncados pelo executor devido ao limite de tamanho]"

        if logs and logs.strip():
            logger.info(f"[SANDBOX {self.id[:12]} OUTPUT - exit {exit_code}]:\n{logs.strip()}")

        return {
            "exit_code": exit_code,
            "logs": logs,
            "container_id": self.id
        }

    def copy_file_to_container(self, src_path: str, dst_path: str) -> bool:
        """
        Copia um arquivo local diretamente para dentro do volume do container usando a API do Docker (docker cp).
        """
        if self.closed:
            raise RuntimeError("Tentativa de copiar arquivo em SandboxSession já encerrada.")

        if not os.path.exists(src_path):
            logger.warning(f"Arquivo de origem não encontrado para cópia: {src_path}")
            return False

        if hasattr(self.container, "put_archive"):
            try:
                import io, tarfile
                dst_dir = os.path.dirname(dst_path) or "/"
                dst_name = os.path.basename(dst_path)

                self.exec(f"mkdir -p '{dst_dir}'")

                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode="w") as tar:
                    tar.add(src_path, arcname=dst_name)
                stream.seek(0)

                return self.container.put_archive(dst_dir, stream.getvalue())
            except Exception as e:
                logger.error(f"Erro ao copiar arquivo {src_path} para o container: {e}")
                return False
        return True

    def copy_directory_to_container(self, src_dir: str, dst_dir: str) -> bool:
        """
        Copia um diretório inteiro local diretamente para o volume do container usando a API do Docker (docker cp).
        """
        if self.closed:
            raise RuntimeError("Tentativa de copiar diretório em SandboxSession já encerrada.")

        if not os.path.exists(src_dir) or not os.path.isdir(src_dir):
            logger.warning(f"Diretório de origem não encontrado para cópia: {src_dir}")
            return False

        if hasattr(self.container, "put_archive"):
            try:
                import io, tarfile
                self.exec(f"mkdir -p '{dst_dir}'")

                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode="w") as tar:
                    for root, _, files in os.walk(src_dir):
                        for file in files:
                            full_path = os.path.join(root, file)
                            rel_path = os.path.relpath(full_path, src_dir)
                            tar.add(full_path, arcname=rel_path)
                stream.seek(0)

                return self.container.put_archive(dst_dir, stream.getvalue())
            except Exception as e:
                logger.error(f"Erro ao copiar diretório {src_dir} para o container: {e}")
                return False
        return True

    def inject_context_bundle(self, context_bundle: Dict[str, Any]) -> None:
        """
        Copia diretórios e arquivos de templates de prompt, MCPs e Skills
        diretamente para o volume do container em /workspace.
        """
        if not context_bundle or not isinstance(context_bundle, dict):
            return

        settings_obj = getattr(self.manager, "settings", global_settings) if self.manager else global_settings

        # 1. Copiar diretório de Prompts para /workspace/prompts
        prompts_dir = str(settings_obj.resolved_prompts_dir)
        if os.path.exists(prompts_dir) and os.path.isdir(prompts_dir):
            self.copy_directory_to_container(prompts_dir, f"{self.working_dir}/prompts")

        # 2. Copiar diretório de Skills para /workspace/.agents/skills
        skills_dir = str(settings_obj.resolved_skills_dir)
        if os.path.exists(skills_dir) and os.path.isdir(skills_dir):
            self.copy_directory_to_container(skills_dir, f"{self.working_dir}/.agents/skills")

        # 3. Copiar MCP Config para /workspace/mcp_config.json
        mcp_path = str(settings_obj.resolved_mcp_config_path)
        if os.path.exists(mcp_path) and os.path.isfile(mcp_path):
            self.copy_file_to_container(mcp_path, f"{self.working_dir}/mcp_config.json")

    def close(self) -> None:
        """Encerra e destrói completamente o container e arquivos temporários."""
        if not self.closed:
            self.closed = True
            if self.manager:
                self.manager.cleanup_sandbox(self.container, self.temp_dir)
            else:
                try:
                    if hasattr(self.container, "stop"):
                        self.container.stop(timeout=5)
                    if hasattr(self.container, "remove"):
                        self.container.remove(v=True, force=True)
                except Exception:
                    pass
                if os.path.exists(self.temp_dir):
                    shutil.rmtree(self.temp_dir, ignore_errors=True)

    def __enter__(self) -> "SandboxSession":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


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

    def create_session(
        self,
        image: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        working_dir: str = "/workspace",
        context_bundle: Optional[Dict[str, Any]] = None,
        entrypoint: Optional[Any] = None,
        command: Optional[Any] = None
    ) -> SandboxSession:
        """
        Cria e inicializa uma SandboxSession persistente mantendo o container em execução
        durante todo o ciclo da história.
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
        volumes = {
            temp_dir: {"bind": working_dir, "mode": "rw"}
        }
        logger.info(f"Criando container sandbox contínuo com imagem {target_image}")

        target_command = command if command is not None else ["/bin/sh", "-c", "tail -f /dev/null"]
        run_kwargs = {
            "image": target_image,
            "command": target_command,
            "environment": final_env,
            "volumes": volumes,
            "working_dir": working_dir,
            "detach": True,
            "auto_remove": False
        }
        if entrypoint is not None:
            run_kwargs["entrypoint"] = entrypoint

        try:
            container = self.client.containers.run(**run_kwargs)
            return SandboxSession(
                container=container,
                temp_dir=temp_dir,
                working_dir=working_dir,
                manager=self
            )
        except Exception as e:
            self.cleanup_sandbox(None, temp_dir)
            raise e

    @contextmanager
    def run_sandbox(
        self,
        image: Optional[str] = None,
        command: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        working_dir: str = "/workspace",
        context_bundle: Optional[Dict[str, Any]] = None,
        entrypoint: Optional[Any] = None
    ) -> Generator[docker.models.containers.Container, None, None]:
        """
        Gerenciador de contexto para execuções únicas efêmeras.
        """
        session = self.create_session(
            image=image,
            env_vars=env_vars,
            working_dir=working_dir,
            context_bundle=context_bundle,
            entrypoint=entrypoint,
            command=command
        )
        try:
            yield session.container
        finally:
            session.close()

    def cleanup_sandbox(self, container: Optional[Any] = None, temp_dir: Optional[str] = None) -> None:
        """
        Teardown completo do container (stop + remove) e destruição de diretórios efêmeros.
        """
        if container:
            try:
                logger.info(f"Encerrando container sandbox {getattr(container, 'id', 'desconhecido')}")
                if hasattr(container, "stop"):
                    container.stop(timeout=5)
            except Exception as e:
                logger.warning(f"Erro ao interromper container {getattr(container, 'id', 'desconhecido')}: {e}")

            try:
                logger.info(f"Removendo container sandbox {getattr(container, 'id', 'desconhecido')}")
                if hasattr(container, "remove"):
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
        context_bundle: Optional[Dict[str, Any]] = None,
        entrypoint: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Executa um comando síncrono dentro do sandbox efêmero, aguarda conclusão, captura logs e faz teardown.
        """
        timeout_val = timeout or self.settings.CONTAINER_TIMEOUT
        with self.run_sandbox(
            image=image,
            command=command,
            env_vars=env_vars,
            context_bundle=context_bundle,
            entrypoint=entrypoint
        ) as container:
            exit_code = -1
            try:
                if hasattr(container, "wait"):
                    res = container.wait(timeout=timeout_val)
                    exit_code = res.get("StatusCode", -1) if isinstance(res, dict) else res
            except Exception as e:
                logger.error(f"Exceção ao aguardar término do container sandbox: {e}")

            try:
                if hasattr(container, "logs"):
                    raw_logs = container.logs(stdout=True, stderr=True)
                    if isinstance(raw_logs, bytes):
                        logs = raw_logs.decode("utf-8", errors="replace")
                    else:
                        logs = str(raw_logs or "")
                else:
                    logs = ""
            except Exception as e:
                logs = f"[Erro ao obter logs: {e}]"

            if len(logs) > max_log_bytes:
                logs = logs[:max_log_bytes] + "\n... [logs truncados pelo executor devido ao limite de tamanho]"

            return {
                "exit_code": exit_code,
                "logs": logs,
                "container_id": getattr(container, "id", None)
            }

    def run_validation(
        self,
        commands: Optional[list[str]] = None,
        image: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        context_bundle: Optional[Dict[str, Any]] = None
    ) -> list[Dict[str, Any]]:
        """
        Executa a lista de comandos de validação sequencialmente dentro de uma única sessão de sandbox.
        """
        cmds = commands if commands is not None else getattr(self.settings, "VALIDATION_COMMANDS", ["pytest"])
        results = []
        with self.create_session(
            image=image,
            env_vars=env_vars,
            context_bundle=context_bundle
        ) as session:
            for cmd in cmds:
                res = session.exec(command=cmd, timeout=timeout)
                res["command"] = cmd
                results.append(res)
                if res.get("exit_code", -1) != 0:
                    logger.warning(f"Comando de validação '{cmd}' falhou no sandbox (exit code {res.get('exit_code')}).")
                    break
        return results
