import json
from typing import Optional
from fastapi import APIRouter, Request, Header, HTTPException, status, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..database import get_async_session
from ..security import validate_github_signature

router = APIRouter()


@router.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED)
async def receive_github_webhook(
    request: Request,
    body_bytes: bytes = Depends(validate_github_signature),
    x_github_event: str = Header(default="unknown", alias="X-GitHub-Event"),
    x_github_delivery: Optional[str] = Header(default=None, alias="X-GitHub-Delivery"),
    session: AsyncSession = Depends(get_async_session)
):
    if not x_github_delivery:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: X-GitHub-Delivery"
        )
    event_type = x_github_event or "unknown"
    event_id = x_github_delivery

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    try:
        stmt = text("""
            INSERT INTO events (event_id, event_type, status, payload, retry_count)
            VALUES (:event_id, :event_type, 'PENDING', :payload, 0)
            RETURNING id, event_id, event_type, status
        """)
        result = await session.execute(stmt, {
            "event_id": event_id,
            "event_type": event_type,
            "payload": json.dumps(payload)
        })
        await session.commit()
        row = result.fetchone()
        return {
            "message": "Event received and persisted",
            "id": str(row.id) if row else None,
            "event_id": row.event_id if row else event_id,
            "event_type": row.event_type if row else event_type,
            "status": row.status if row else "PENDING"
        }
    except IntegrityError:
        await session.rollback()
        return {
            "message": "Event already processed (idempotent duplicate)",
            "event_id": event_id,
            "event_type": event_type,
            "status": "PENDING"
        }
