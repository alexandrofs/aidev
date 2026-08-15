import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from persistence.src.repository import EventRepository
from executor.src.config import ExecutorSettings, settings as global_settings

try:
    import fcntl
except ImportError:
    fcntl = None

logger = logging.getLogger(__name__)

# F6: Lock de módulo para serializar escritas no arquivo .memlog.md
# Protege contra race conditions quando asyncio.to_thread() dispara múltiplas
# escritas concorrentes no mesmo arquivo (múltiplos workers no mesmo processo).
_memlog_write_lock = threading.Lock()


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
        summary_data: Dict[str, Any],
        event_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Grava o resumo de memória estruturada no banco de dados (Nível 2).

        Idempotência (F5): quando `event_id` é fornecido, o repositório faz UPSERT
        garantindo que retries do mesmo evento não criem duplicatas.
        """
        payload = dict(summary_data)
        if "timestamp" not in payload:
            payload["timestamp"] = datetime.now(timezone.utc).isoformat()

        logger.info(f"Gravando resumo diário de memória para a história '{story_id}' no repositório DB.")
        saved = await self.repo.save_agent_memory(
            story_id=story_id,
            memory_type="daily_summary",
            content=payload,
            event_id=event_id
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

        F5: Verifica se já existe uma entrada com o mesmo timestamp antes de fazer append,
        evitando duplicatas em retries.

        F6: Usa _memlog_write_lock para serializar escritas e evitar race conditions
        quando múltiplos workers no mesmo processo tentam escrever simultaneamente.
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

        # Metadados de Code Review (Story 3.1 AC: 4)
        review_data = summary_data.get("review_summary")
        review_line = ""
        if isinstance(review_data, dict):
            rev_status = review_data.get("status", "APPROVED")
            patches = review_data.get("patches_applied", 0)
            findings = review_data.get("findings_count", 0)
            deferred = review_data.get("deferred_count", 0)
            review_line = f"- **Code Review Interno:** Status: {rev_status} | Achados: {findings} | Patches Aplicados: {patches} | Diferidos: {deferred}\n"
        elif "review_status" in summary_data:
            review_line = f"- **Code Review Interno:** {summary_data.get('review_status')}\n"

        # Metadados de Pull Request (Story 3.2 AC: 4)
        pr_url = summary_data.get("pr_url")
        pr_number = summary_data.get("pr_number")
        pr_line = ""
        if pr_url:
            pr_num_str = f" #{pr_number}" if pr_number else ""
            pr_line = f"- **Pull Request:** [PR{pr_num_str}]({pr_url}) (Aguardando Revisão Humana)\n"

        # Cabeçalho único da entrada — usado para verificar duplicata
        entry_header = f"## [{timestamp}] - Story {story_id}: {title}"
        entry_md = (
            f"{entry_header}\n"
            f"- **Status:** {status}\n"
            f"- **Ações Realizadas:** {actions}\n"
            f"{review_line}"
            f"{pr_line}"
            f"- **Resultado dos Testes:** {test_results}\n"
            f"- **Aprendizados/Decisões:** {decisions}\n\n"
        )

        try:
            memlog_path.parent.mkdir(parents=True, exist_ok=True)

            # F6: Lock de thread + File lock em nível de SO (fcntl.flock) para serializar escritas
            # concorrentes entre múltiplos processos e workers paralelos.
            with _memlog_write_lock:
                with open(memlog_path, "a+", encoding="utf-8") as f:
                    if fcntl:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        # F5: verificar se já existe entrada com o mesmo cabeçalho (idempotência em retries)
                        f.seek(0)
                        existing_content = f.read()

                        if entry_header in existing_content:
                            logger.info(
                                f"Entrada para '{story_id}' com timestamp '{timestamp}' já existe "
                                f"em {memlog_path}. Pulando append (idempotência de retry)."
                            )
                            return memlog_path

                        f.seek(0, 2)  # Seek to end of file
                        f.write(entry_md)
                        f.flush()
                    finally:
                        if fcntl:
                            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            logger.info(f"Arquivo de memória .memlog.md atualizado com sucesso em: {memlog_path}")
        except Exception as e:
            logger.error(f"Erro ao escrever arquivo .memlog.md em {memlog_path}: {e}")
            raise

        return memlog_path
