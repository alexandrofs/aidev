import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from executor.src.config import settings, ExecutorSettings
from executor.src.exceptions import ContextError, PromptTemplateNotFoundError, InvalidMCPConfigError

logger = logging.getLogger(__name__)


def render_prompt_template(
    template_content: str,
    issue_id: Optional[str] = None,
    task_description: Optional[str] = None
) -> str:
    """
    Substitui com segurança as variáveis de contexto no template de prompt.
    {ISSUE_ID} -> ID/número da issue
    {TASK_DESCRIPTION} -> Descrição da tarefa
    """
    rendered = template_content
    effective_issue_id = str(issue_id).strip() if issue_id is not None else ""
    effective_task_desc = str(task_description).strip() if task_description is not None else ""

    rendered = rendered.replace("{ISSUE_ID}", effective_issue_id)
    rendered = rendered.replace("{TASK_DESCRIPTION}", effective_task_desc)
    return rendered


class ContextLoader:
    def __init__(self, settings_override: Optional[ExecutorSettings] = None):
        self.settings = settings_override or settings

    def load_mcp_config(self, mcp_config_path: Optional[str] = None) -> Dict[str, Any]:
        """Loads and validates MCP server configuration file."""
        target_path = Path(mcp_config_path) if mcp_config_path else getattr(self.settings, "resolved_mcp_config_path", Path(self.settings.MCP_CONFIG_PATH))
        if not target_path.exists():
            logger.info(f"MCP configuration file not found at {target_path}. Using empty MCP configuration.")
            return {}

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise InvalidMCPConfigError(f"Formato de JSON inválido em {target_path}: esperado objeto JSON (dict).")
            return data
        except json.JSONDecodeError as err:
            logger.error(f"Erro ao interpretar JSON no arquivo MCP {target_path}: {err}")
            raise InvalidMCPConfigError(f"Arquivo de configuração MCP contém JSON inválido: {err}") from err
        except Exception as err:
            if isinstance(err, InvalidMCPConfigError):
                raise
            logger.error(f"Erro inesperado ao carregar arquivo MCP {target_path}: {err}")
            raise InvalidMCPConfigError(f"Falha ao carregar MCP config: {err}") from err

    def discover_skills(self, skills_dir: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Scans skills directory for subdirectories containing SKILL.md."""
        target_dir = Path(skills_dir) if skills_dir else getattr(self.settings, "resolved_skills_dir", Path(self.settings.SKILLS_DIR))
        skills_catalog: Dict[str, Dict[str, Any]] = {}

        if not target_dir.exists() or not target_dir.is_dir():
            logger.info(f"Diretório de skills não encontrado em {target_dir}. Retornando catálogo vazio.")
            return skills_catalog

        for item in target_dir.iterdir():
            if item.is_dir():
                skill_file = item / "SKILL.md"
                if skill_file.exists() and skill_file.is_file():
                    try:
                        content = skill_file.read_text(encoding="utf-8")
                        skills_catalog[item.name] = {
                            "name": item.name,
                            "path": str(item.resolve()),
                            "content": content
                        }
                    except Exception as err:
                        logger.warning(f"Erro ao ler SKILL.md em {item}: {err}")

        return skills_catalog

    def load_prompt_template(self, phase: str, prompts_dir: Optional[str] = None) -> str:
        """Loads and validates a prompt template for a specific workflow phase."""
        target_dir = Path(prompts_dir) if prompts_dir else getattr(self.settings, "resolved_prompts_dir", Path(self.settings.PROMPTS_DIR))
        clean_phase = os.path.basename(phase)
        filename = clean_phase if clean_phase.endswith(".md") else f"{clean_phase}.md"
        prompt_path = target_dir / filename

        if not prompt_path.exists():
            msg = f"Prompt obrigatório ausente: template para a fase '{phase}' ({filename}) não existe em {target_dir}."
            logger.error(msg)
            raise PromptTemplateNotFoundError(msg)

        try:
            content = prompt_path.read_text(encoding="utf-8")
        except Exception as err:
            msg = f"Falha ao ler o template de prompt {prompt_path}: {err}"
            logger.error(msg)
            raise PromptTemplateNotFoundError(msg) from err

        if not content.strip():
            msg = f"Template de prompt '{filename}' em {target_dir} está vazio (0 bytes de conteúdo útil)."
            logger.error(msg)
            raise PromptTemplateNotFoundError(msg)

        return content

    def validate_mandatory_prompts(self, prompts_dir: Optional[str] = None) -> None:
        """Validates that all required prompts exist and are non-empty."""
        for mandatory_prompt in self.settings.MANDATORY_PROMPTS:
            phase_name = Path(mandatory_prompt).stem
            self.load_prompt_template(phase_name, prompts_dir=prompts_dir)

    def build_context_bundle(
        self,
        phase: str,
        base_dir: Optional[str] = None,
        issue_id: Optional[str] = None,
        task_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Compiles complete context bundle with MCPs, Skills and phase Prompt."""
        prompts_dir = str(Path(base_dir) / self.settings.PROMPTS_DIR) if base_dir else None
        skills_dir = str(Path(base_dir) / self.settings.SKILLS_DIR) if base_dir else None
        mcp_path = str(Path(base_dir) / self.settings.MCP_CONFIG_PATH) if base_dir else None

        self.validate_mandatory_prompts(prompts_dir=prompts_dir)
        prompt_content = self.load_prompt_template(phase, prompts_dir=prompts_dir)
        if issue_id is not None or task_description is not None:
            prompt_content = render_prompt_template(prompt_content, issue_id=issue_id, task_description=task_description)

        mcp_config = self.load_mcp_config(mcp_config_path=mcp_path)
        skills_catalog = self.discover_skills(skills_dir=skills_dir)

        # Collect all mandatory prompt contents for the bundle
        prompts_dict = {}
        for p_name in self.settings.MANDATORY_PROMPTS:
            phase_key = Path(p_name).stem
            raw_prompt = self.load_prompt_template(phase_key, prompts_dir=prompts_dir)
            if issue_id is not None or task_description is not None:
                raw_prompt = render_prompt_template(raw_prompt, issue_id=issue_id, task_description=task_description)
            prompts_dict[phase_key] = raw_prompt

        return {
            "phase": phase,
            "prompt_template": prompt_content,
            "mcp_config": mcp_config,
            "skills": skills_catalog,
            "prompts": prompts_dict
        }

