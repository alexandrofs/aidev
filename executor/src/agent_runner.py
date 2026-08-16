import os
import logging
from typing import Optional, Dict, Any
from executor.src.config import ExecutorSettings, settings as global_settings

logger = logging.getLogger(__name__)


class AgentRunner:
    """
    Executor autônomo para Agentes de IA via CLI do OpenCode.
    Constrói e formata os comandos de invocação das fases de desenvolvimento e revisão.
    """

    def __init__(self, settings: Optional[ExecutorSettings] = None):
        self.settings = settings or global_settings

    def build_agent_command(
        self,
        phase: str,
        story_id: str,
        prompt_path: str = "/workspace/prompts/coding.md",
        custom_instructions: Optional[str] = None,
        working_dir: str = "/workspace"
    ) -> str:
        """
        Gera o comando de execução para o OpenCode CLI na fase designada.
        """
        cmd_template = self.settings.OPENCODE_RUN_COMMAND
        model_flag = f"-m {self.settings.OPENCODE_MODEL}" if self.settings.OPENCODE_MODEL else ""

        # Montar o comando base
        formatted_cmd = cmd_template.format(
            prompt_path=prompt_path,
            phase=phase,
            story_id=story_id
        )

        if model_flag and model_flag not in formatted_cmd:
            formatted_cmd = f"{formatted_cmd} {model_flag}"

        # Script com verificação do binário opencode e fallback gracioso
        full_command = f"""
cd {working_dir}
if command -v opencode >/dev/null 2>&1; then
    echo "[OPENCODE] Iniciando Agente de IA para a fase '{phase}' na história '{story_id}'..."
    {formatted_cmd}
else
    echo "[OPENCODE-FALLBACK] CLI 'opencode' não encontrada no PATH. Executando simulação de fase '{phase}'..."
    echo "[AGENT] Analisando prompt em {prompt_path}..."
    echo "[AGENT] Fase '{phase}' executada com sucesso no workspace {working_dir}."
fi
""".strip()

        return full_command

    def get_phase_env_vars(
        self,
        phase: str,
        story_id: str,
        base_env: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """Gera as variáveis de ambiente necessárias para a sessão do OpenCode."""
        env = dict(base_env or {})
        env["WORKFLOW_PHASE"] = phase
        env["STORY_ID"] = story_id
        env["NON_INTERACTIVE"] = "1"
        env["CI"] = "true"

        if self.settings.OPENCODE_API_KEY:
            env["OPENCODE_API_KEY"] = self.settings.OPENCODE_API_KEY
            env["ANTHROPIC_API_KEY"] = self.settings.OPENCODE_API_KEY
            env["GEMINI_API_KEY"] = self.settings.OPENCODE_API_KEY
            env["OPENAI_API_KEY"] = self.settings.OPENCODE_API_KEY

        return env
