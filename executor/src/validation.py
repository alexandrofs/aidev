import time
import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from executor.src.config import ExecutorSettings, settings as global_settings
from executor.src.sandbox import DockerSandboxManager

logger = logging.getLogger(__name__)


class ValidationResult(BaseModel):
    passed: bool
    command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    duration_seconds: float = 0.0


class ValidationPipeline:
    """
    Pipeline de Validação Local pré-entrega.
    Executa a suíte de testes e linters configurados dentro do sandbox efêmero Docker.
    """

    def __init__(
        self,
        sandbox_manager: Optional[DockerSandboxManager] = None,
        settings: Optional[ExecutorSettings] = None
    ):
        self.settings = settings or global_settings
        self.sandbox_manager = sandbox_manager or DockerSandboxManager(settings=self.settings)

    def execute_command(
        self,
        command: str,
        image: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        context_bundle: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Executa um único comando de validação no sandbox efêmero e retorna um ValidationResult estruturado.
        """
        start_time = time.time()
        try:
            res = self.sandbox_manager.execute_job(
                command=command,
                image=image,
                env_vars=env_vars,
                timeout=timeout,
                context_bundle=context_bundle
            )
            duration = time.time() - start_time
            exit_code = res.get("exit_code", -1)
            logs = res.get("logs", "")
            passed = (exit_code == 0)

            return ValidationResult(
                passed=passed,
                command=command,
                # F3: logs do sandbox preenchidos em ambos os campos — stdout e stderr
                # não é possível separar com fidelidade a partir do campo único 'logs'
                stdout=logs,
                stderr=logs if not passed else "",
                exit_code=exit_code,
                duration_seconds=round(duration, 3)
            )
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Exceção ao executar comando de validação '{command}': {e}")
            return ValidationResult(
                passed=False,
                command=command,
                stdout="",
                stderr=f"Exceção na execução da validação: {str(e)}",
                exit_code=-1,
                duration_seconds=round(duration, 3)
            )

    def run_validations(
        self,
        commands: Optional[List[str]] = None,
        image: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        context_bundle: Optional[Dict[str, Any]] = None
    ) -> List[ValidationResult]:
        """
        Executa sequencialmente a lista de comandos de validação.
        Retorna a lista de ValidationResults.
        """
        cmds = commands if commands is not None else getattr(self.settings, "VALIDATION_COMMANDS", ["pytest"])
        results = []
        for cmd in cmds:
            result = self.execute_command(
                command=cmd,
                image=image,
                env_vars=env_vars,
                timeout=timeout,
                context_bundle=context_bundle
            )
            results.append(result)
            if not result.passed:
                logger.warning(f"Validação falhou no comando '{cmd}'. Interrompendo pipeline.")
                break
        return results
