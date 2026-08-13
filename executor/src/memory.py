import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from persistence.src.repository import EventRepository
from executor.src.config import ExecutorSettings, settings as global_settings

logger = logging.getLogger(__name__)


class AgentMemoryManager:
    """
    Gerenciador de Memória Hierárquica Diária do Agente.
    Nível 2: Persistência estruturada em PostgreSQL (tabela agent_memory via EventRepository).
    Nível 3: Sincronização em arquivo Markdown (.memlog.md) no repositório.
    """

    def __init__(
        self,
        repo: EventRepository,
        settings: Optional[ExecutorSettings] = None
    ):
        self.repo = repo
        self.settings = settings or global_settings

    async def record_daily_summary(
        self,
        story_id: str,
        summary_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Grava o resumo de memória estruturada no banco de dados (Nível 2).
        """
        payload = dict(summary_data)
        if "timestamp" not in payload:
            payload["timestamp"] = datetime.now(timezone.utc).isoformat()

        logger.info(f"Gravando resumo diário de memória para a história '{story_id}' no repositório DB.")
        saved = await self.repo.save_agent_memory(
            story_id=story_id,
            memory_type="daily_summary",
            content=payload
        )
        return saved

    def sync_memlog_file(
        self,
        workspace_path: Path,
        story_id: str,
        summary_data: Dict[str, Any]
    ) -> Path:
        """
        Formata e realiza append do resumo no arquivo .memlog.md na raiz do workspace (Nível 3).
        Preserva entradas anteriores.
        """
        memlog_filename = getattr(self.settings, "MEMLOG_FILENAME", ".memlog.md")
        memlog_path = Path(workspace_path) / memlog_filename

        timestamp = summary_data.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        title = summary_data.get("title") or summary_data.get("story_title") or story_id
        status = summary_data.get("status", "COMPLETED")

        actions = summary_data.get("actions", "Nenhuma ação detalhada")
        if isinstance(actions, list):
            actions = "; ".join(str(a) for a in actions)

        test_results = summary_data.get("test_results", "Sem registros de teste")
        if isinstance(test_results, dict):
            passed = test_results.get("passed", 0)
            failed = test_results.get("failed", 0)
            test_results = f"{passed} passed, {failed} failed"

        decisions = summary_data.get("decisions") or summary_data.get("notes") or "Nenhuma observação registrada"
        if isinstance(decisions, list):
            decisions = "; ".join(str(d) for d in decisions)

        entry_md = (
            f"## [{timestamp}] - Story {story_id}: {title}\n"
            f"- **Status:** {status}\n"
            f"- **Ações Realizadas:** {actions}\n"
            f"- **Resultado dos Testes:** {test_results}\n"
            f"- **Aprendizados/Decisões:** {decisions}\n\n"
        )

        try:
            memlog_path.parent.mkdir(parents=True, exist_ok=True)
            with open(memlog_path, "a", encoding="utf-8") as f:
                f.write(entry_md)
            logger.info(f"Arquivo de memória .memlog.md atualizado com sucesso em: {memlog_path}")
        except Exception as e:
            logger.error(f"Erro ao escrever arquivo .memlog.md em {memlog_path}: {e}")
            raise

        return memlog_path
