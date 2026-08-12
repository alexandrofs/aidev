import json
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, bindparam


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
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Insere um registro de auditoria na tabela audit_logs."""
        log_id = str(uuid.uuid4())
        details_str = json.dumps(details) if details is not None else None

        stmt = text("""
            INSERT INTO audit_logs (id, event_id, action, actor, details, created_at)
            VALUES (:id, :event_id, :action, :actor, :details, :created_at)
        """)
        await self.session.execute(stmt, {
            "id": log_id,
            "event_id": event_id,
            "action": action,
            "actor": actor,
            "details": details_str,
            "created_at": datetime.now(timezone.utc)
        })

    async def claim_event(
        self,
        event_types: List[str],
        worker_id: str,
        skip_locked: bool = True
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
                RETURNING events.id, events.event_id, events.event_type, events.status, events.payload, events.retry_count, events.created_at, events.updated_at;
            """)
            result = await self.session.execute(query, {"event_types": event_types})
            row = result.fetchone()
            if not row:
                return None

            payload_dict = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
            event_rec = EventRecord(
                id=str(row.id),
                event_id=row.event_id,
                event_type=row.event_type,
                status=row.status,
                payload=payload_dict,
                retry_count=row.retry_count,
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
                RETURNING id, event_id, event_type, status, payload, retry_count, created_at, updated_at
            """).bindparams(bindparam("types", expanding=True))

            try:
                result = await self.session.execute(stmt, {"types": event_types})
                row = result.fetchone()
            except Exception:
                # Se o dialeto SQLite não suportar RETURNING ou subquery em UPDATE
                row = None

            if not row:
                return None

            payload_dict = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
            event_rec = EventRecord(
                id=str(row.id),
                event_id=row.event_id,
                event_type=row.event_type,
                status="PROCESSING",
                payload=payload_dict,
                retry_count=row.retry_count,
                created_at=row.created_at,
                updated_at=row.updated_at
            )

        # Audit Log
        await self.add_audit_log(
            event_id=event_rec.event_id,
            action="CLAIMED",
            actor=worker_id,
            details={"event_type": event_rec.event_type}
        )
        await self.session.commit()
        return event_rec

    async def complete_event(
        self,
        event_id: str,
        worker_id: str,
        details: Optional[Dict[str, Any]] = None
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
                details=details
            )
            await self.session.commit()
            return True
        return False

    async def fail_event(
        self,
        event_id: str,
        worker_id: str,
        error_message: str,
        max_retries: int = 3
    ) -> bool:
        """
        Trata falha de evento. Incrementa retry_count.
        Se retry_count < max_retries, retorna a PENDING (action: RETRY).
        Caso contrário, define status FAILED (action: FAILED).
        """
        stmt_select = text("SELECT retry_count FROM events WHERE event_id = :event_id")
        res = await self.session.execute(stmt_select, {"event_id": event_id})
        row = res.fetchone()
        if not row:
            return False

        current_retries = row.retry_count
        new_retries = current_retries + 1

        if new_retries < max_retries:
            new_status = "PENDING"
            action = "RETRY"
        else:
            new_status = "FAILED"
            action = "FAILED"

        stmt_update = text("""
            UPDATE events
            SET status = :status, retry_count = :retry_count, updated_at = CURRENT_TIMESTAMP
            WHERE event_id = :event_id
        """)
        await self.session.execute(stmt_update, {
            "status": new_status,
            "retry_count": new_retries,
            "event_id": event_id
        })

        audit_details = {"error": error_message, "retry_count": new_retries}
        await self.add_audit_log(
            event_id=event_id,
            action=action,
            actor=worker_id,
            details=audit_details
        )
        await self.session.commit()
        return True

    async def check_idempotency(
        self,
        event_id: Optional[str] = None,
        payload_hash: Optional[str] = None
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

        if payload_hash:
            stmt = text("""
                SELECT payload FROM events
                WHERE status IN ('PROCESSING', 'COMPLETED')
            """)
            res = await self.session.execute(stmt)
            rows = res.fetchall()
            for row in rows:
                p = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
                if compute_payload_hash(p) == payload_hash:
                    return True

        return False
