import json
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, bindparam, JSON, String
from sqlalchemy.dialects.postgresql import ARRAY

logger = logging.getLogger(__name__)


def compute_payload_hash(payload: Dict[str, Any]) -> str:
    """Retorna hash SHA-256 determinístico de um dicionário JSON."""
    canonical_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()


class EventRecord(BaseModel):
    id: str
    event_id: str
    event_type: str
    status: str
    payload: Dict[str, Any]
    retry_count: int = 0
    error_log: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_audit_log(
        self,
        event_id: Optional[str],
        action: str,
        actor: str,
        details: Optional[Dict[str, Any]] = None,
        auto_commit: bool = True
    ) -> None:
        """Insere um registro de auditoria na tabela audit_logs."""
        log_id = str(uuid.uuid4())

        stmt = text("""
            INSERT INTO audit_logs (id, event_id, action, actor, details, created_at)
            VALUES (:id, :event_id, :action, :actor, :details, :created_at)
        """).bindparams(bindparam("details", type_=JSON))

        await self.session.execute(stmt, {
            "id": log_id,
            "event_id": event_id,
            "action": action,
            "actor": actor,
            "details": details,
            "created_at": datetime.now(timezone.utc)
        })
        if auto_commit:
            await self.session.commit()

    async def claim_event(
        self,
        event_types: List[str],
        worker_id: str,
        skip_locked: bool = True,
        auto_commit: bool = True
    ) -> Optional[EventRecord]:
        """
        Seleciona e trava atomicamente um evento em status PENDING filtrando por tipos.
        Atualiza o status para 'PROCESSING' e grava log de auditoria 'CLAIMED'.
        """
        if not event_types:
            return None

        is_postgres = self.session.bind and "postgresql" in self.session.bind.dialect.name.lower()

        if is_postgres:
            lock_clause = "FOR UPDATE SKIP LOCKED" if skip_locked else "FOR UPDATE"
            query = text(f"""
                WITH eligible AS (
                    SELECT id 
                    FROM events 
                    WHERE status = 'PENDING' 
                      AND event_type = ANY(:event_types)
                    ORDER BY created_at ASC
                    LIMIT 1
                    {lock_clause}
                )
                UPDATE events
                SET status = 'PROCESSING',
                    updated_at = NOW()
                FROM eligible
                WHERE events.id = eligible.id
                RETURNING events.id, events.event_id, events.event_type, events.status, events.payload, events.retry_count, events.created_at, events.updated_at, events.error_log;
            """).bindparams(bindparam("event_types", type_=ARRAY(String)))
            try:
                result = await self.session.execute(query, {"event_types": event_types})
                row = result.fetchone()
            except Exception:
                await self.session.rollback()
                raise
            if not row:
                await self.session.rollback()
                return None

            payload_dict = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
            event_rec = EventRecord(
                id=str(row.id),
                event_id=row.event_id,
                event_type=row.event_type,
                status=row.status,
                payload=payload_dict,
                retry_count=row.retry_count,
                error_log=getattr(row, "error_log", None),
                created_at=row.created_at,
                updated_at=row.updated_at
            )
        else:
            # Fallback atômico via subquery em SQLite / dialetos sem CTE SKIP LOCKED
            stmt = text("""
                UPDATE events
                SET status = 'PROCESSING', updated_at = CURRENT_TIMESTAMP
                WHERE id = (
                    SELECT id FROM events
                    WHERE status = 'PENDING' AND event_type IN :types
                    ORDER BY created_at ASC
                    LIMIT 1
                )
                RETURNING id, event_id, event_type, status, payload, retry_count, created_at, updated_at, error_log
            """).bindparams(bindparam("types", expanding=True))

            try:
                result = await self.session.execute(stmt, {"types": event_types})
                row = result.fetchone()
            except Exception as exc:
                logger.warning("SQL execution in claim_event fallback failed: %s", exc)
                # Fallback secundário se coluna error_log não existir em schemas antigos SQLite
                try:
                    stmt_legacy = text("""
                        UPDATE events
                        SET status = 'PROCESSING', updated_at = CURRENT_TIMESTAMP
                        WHERE id = (
                            SELECT id FROM events
                            WHERE status = 'PENDING' AND event_type IN :types
                            ORDER BY created_at ASC
                            LIMIT 1
                        )
                        RETURNING id, event_id, event_type, status, payload, retry_count, created_at, updated_at
                    """).bindparams(bindparam("types", expanding=True))
                    result_legacy = await self.session.execute(stmt_legacy, {"types": event_types})
                    row = result_legacy.fetchone()
                except Exception:
                    await self.session.rollback()
                    row = None

            if not row:
                await self.session.rollback()
                return None

            payload_dict = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
            event_rec = EventRecord(
                id=str(row.id),
                event_id=row.event_id,
                event_type=row.event_type,
                status="PROCESSING",
                payload=payload_dict,
                retry_count=row.retry_count,
                error_log=getattr(row, "error_log", None),
                created_at=row.created_at,
                updated_at=row.updated_at
            )

        # Audit Log
        try:
            await self.add_audit_log(
                event_id=event_rec.event_id,
                action="CLAIMED",
                actor=worker_id,
                details={"event_type": event_rec.event_type},
                auto_commit=False
            )
            if auto_commit:
                await self.session.commit()
            return event_rec
        except Exception:
            await self.session.rollback()
            raise

    async def complete_event(
        self,
        event_id: str,
        worker_id: str,
        details: Optional[Dict[str, Any]] = None,
        auto_commit: bool = True
    ) -> bool:
        """Marca o evento como COMPLETED e grava log de auditoria."""
        stmt = text("""
            UPDATE events
            SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP
            WHERE event_id = :event_id
        """)
        result = await self.session.execute(stmt, {"event_id": event_id})
        if result.rowcount > 0:
            await self.add_audit_log(
                event_id=event_id,
                action="COMPLETED",
                actor=worker_id,
                details=details,
                auto_commit=False
            )
            if auto_commit:
                await self.session.commit()
            return True
        return False

    async def fail_event(
        self,
        event_id: str,
        worker_id: str,
        error_message: str,
        max_retries: int = 3,
        auto_commit: bool = True
    ) -> bool:
        """
        Trata falha de evento atomicamente. Incrementa retry_count e grava error_log.
        Se retry_count < max_retries, retorna a PENDING (action: RETRY).
        Caso contrário, define status FAILED (action: FAILED).
        """
        stmt_update = text("""
            UPDATE events
            SET retry_count = retry_count + 1,
                status = CASE WHEN (retry_count + 1) < :max_retries THEN 'PENDING' ELSE 'FAILED' END,
                error_log = :error_message,
                updated_at = CURRENT_TIMESTAMP
            WHERE event_id = :event_id
            RETURNING retry_count, status, error_log;
        """)
        
        try:
            res = await self.session.execute(stmt_update, {
                "event_id": event_id,
                "error_message": error_message,
                "max_retries": max_retries
            })
            row = res.fetchone()
        except Exception:
            # Fallback para SQLite sem suporte a RETURNING em UPDATE
            stmt_fallback = text("""
                UPDATE events
                SET retry_count = retry_count + 1,
                    status = CASE WHEN (retry_count + 1) < :max_retries THEN 'PENDING' ELSE 'FAILED' END,
                    error_log = :error_message,
                    updated_at = CURRENT_TIMESTAMP
                WHERE event_id = :event_id
            """)
            try:
                res = await self.session.execute(stmt_fallback, {
                    "event_id": event_id,
                    "error_message": error_message,
                    "max_retries": max_retries
                })
            except Exception:
                # Caso a tabela não possua error_log (schemas antigos)
                stmt_fallback_legacy = text("""
                    UPDATE events
                    SET retry_count = retry_count + 1,
                        status = CASE WHEN (retry_count + 1) < :max_retries THEN 'PENDING' ELSE 'FAILED' END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE event_id = :event_id
                """)
                res = await self.session.execute(stmt_fallback_legacy, {
                    "event_id": event_id,
                    "max_retries": max_retries
                })

            if res.rowcount == 0:
                return False

            res_check = await self.session.execute(
                text("SELECT retry_count, status FROM events WHERE event_id = :event_id"),
                {"event_id": event_id}
            )
            row = res_check.fetchone()

        if not row:
            return False

        new_retries = row.retry_count
        new_status = row.status
        action = "RETRY" if new_status == "PENDING" else "FAILED"

        audit_details = {"error": error_message, "retry_count": new_retries}
        await self.add_audit_log(
            event_id=event_id,
            action=action,
            actor=worker_id,
            details=audit_details,
            auto_commit=False
        )
        if auto_commit:
            await self.session.commit()
        return True

    async def check_idempotency(
        self,
        event_id: Optional[str] = None,
        payload_hash: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        recent_limit: int = 100
    ) -> bool:
        """
        Verifica se um evento com o mesmo event_id ou payload_hash já foi processado ou está em processamento.
        """
        if event_id:
            stmt = text("""
                SELECT 1 FROM events
                WHERE event_id = :event_id AND status IN ('PROCESSING', 'COMPLETED')
                LIMIT 1
            """)
            res = await self.session.execute(stmt, {"event_id": event_id})
            if res.fetchone() is not None:
                return True

        target_hash = payload_hash
        if not target_hash and payload:
            target_hash = compute_payload_hash(payload)

        if target_hash:
            stmt = text("""
                SELECT payload FROM events
                WHERE status IN ('PROCESSING', 'COMPLETED')
                ORDER BY created_at DESC
                LIMIT :recent_limit
            """)
            res = await self.session.execute(stmt, {"recent_limit": recent_limit})
            rows = res.fetchall()
            for row in rows:
                p = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
                if compute_payload_hash(p) == target_hash:
                    return True

        return False

    async def save_agent_memory(
        self,
        story_id: str,
        memory_type: str,
        content: Dict[str, Any],
        event_id: Optional[str] = None,
        auto_commit: bool = True
    ) -> Dict[str, Any]:
        """
        Salva um registro de memória na tabela agent_memory.
        Suporta PostgreSQL (JSONB + UPSERT via ON CONFLICT) e SQLite (JSON/Text) para testes.

        Idempotência (F5): quando `event_id` é fornecido, o UPSERT garante que retries
        do mesmo evento não criem duplicatas — o content é atualizado no conflito.
        """
        mem_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        is_postgres = (
            self.session.bind is not None
            and "postgresql" in self.session.bind.dialect.name.lower()
        )

        if is_postgres and event_id:
            # PostgreSQL: UPSERT — ON CONFLICT (story_id, memory_type, event_id) WHERE event_id IS NOT NULL
            stmt = text("""
                INSERT INTO agent_memory (id, story_id, memory_type, content, event_id, created_at, updated_at)
                VALUES (:id, :story_id, :memory_type, :content, :event_id, :created_at, :updated_at)
                ON CONFLICT (story_id, memory_type, event_id) WHERE event_id IS NOT NULL
                DO UPDATE SET
                    content = EXCLUDED.content,
                    updated_at = EXCLUDED.updated_at
                RETURNING id
            """).bindparams(bindparam("content", type_=JSON))

            result = await self.session.execute(stmt, {
                "id": mem_id,
                "story_id": story_id,
                "memory_type": memory_type,
                "content": content,
                "event_id": event_id,
                "created_at": now,
                "updated_at": now,
            })
            row = result.fetchone()
            if row:
                mem_id = str(row.id)
        else:
            # SQLite fallback e PostgreSQL sem event_id: INSERT simples
            # Para SQLite com event_id: verificar existência antes de inserir
            if event_id:
                check_stmt = text("""
                    SELECT id FROM agent_memory
                    WHERE story_id = :story_id AND memory_type = :memory_type AND event_id = :event_id
                    LIMIT 1
                """)
                check_result = await self.session.execute(check_stmt, {
                    "story_id": story_id,
                    "memory_type": memory_type,
                    "event_id": event_id
                })
                existing = check_result.fetchone()
                if existing:
                    # Atualiza o registro existente
                    mem_id = str(existing.id)
                    update_stmt = text("""
                        UPDATE agent_memory
                        SET content = :content, updated_at = :updated_at
                        WHERE id = :id
                    """).bindparams(bindparam("content", type_=JSON))
                    await self.session.execute(update_stmt, {
                        "id": mem_id,
                        "content": content,
                        "updated_at": now
                    })
                    if auto_commit:
                        await self.session.commit()
                    return {
                        "id": mem_id,
                        "story_id": story_id,
                        "memory_type": memory_type,
                        "content": content,
                        "event_id": event_id,
                        "created_at": now,
                        "updated_at": now,
                    }

            # INSERT simples (sem event_id, ou event_id novo)
            try:
                stmt = text("""
                    INSERT INTO agent_memory (id, story_id, memory_type, content, event_id, created_at, updated_at)
                    VALUES (:id, :story_id, :memory_type, :content, :event_id, :created_at, :updated_at)
                """).bindparams(bindparam("content", type_=JSON))
                await self.session.execute(stmt, {
                    "id": mem_id,
                    "story_id": story_id,
                    "memory_type": memory_type,
                    "content": content,
                    "event_id": event_id,
                    "created_at": now,
                    "updated_at": now,
                })
            except Exception:
                # Fallback para schema sem coluna event_id (SQLite em testes legados)
                stmt_legacy = text("""
                    INSERT INTO agent_memory (id, story_id, memory_type, content, created_at, updated_at)
                    VALUES (:id, :story_id, :memory_type, :content, :created_at, :updated_at)
                """).bindparams(bindparam("content", type_=JSON))
                await self.session.execute(stmt_legacy, {
                    "id": mem_id,
                    "story_id": story_id,
                    "memory_type": memory_type,
                    "content": content,
                    "created_at": now,
                    "updated_at": now,
                })

        if auto_commit:
            await self.session.commit()

        return {
            "id": mem_id,
            "story_id": story_id,
            "memory_type": memory_type,
            "content": content,
            "event_id": event_id,
            "created_at": now,
            "updated_at": now,
        }

    async def get_agent_memory(
        self,
        story_id: str,
        memory_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Busca registros de memória na tabela agent_memory por story_id e (opcionalmente) memory_type.
        """
        if memory_type:
            stmt = text("""
                SELECT id, story_id, memory_type, content, created_at, updated_at
                FROM agent_memory
                WHERE story_id = :story_id AND memory_type = :memory_type
                ORDER BY created_at ASC
            """)
            res = await self.session.execute(stmt, {"story_id": story_id, "memory_type": memory_type})
        else:
            stmt = text("""
                SELECT id, story_id, memory_type, content, created_at, updated_at
                FROM agent_memory
                WHERE story_id = :story_id
                ORDER BY created_at ASC
            """)
            res = await self.session.execute(stmt, {"story_id": story_id})

        rows = res.fetchall()
        results = []
        for row in rows:
            content_dict = row.content if isinstance(row.content, dict) else json.loads(row.content)
            results.append({
                "id": str(row.id),
                "story_id": row.story_id,
                "memory_type": row.memory_type,
                "content": content_dict,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            })
        return results

