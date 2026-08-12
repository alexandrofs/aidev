import hmac
import hashlib
from typing import Optional
from fastapi import Request, HTTPException, status, Header
from .config import settings


def verify_github_signature(secret: str, body: bytes, signature_header: Optional[str]) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature_header)


async def validate_github_signature(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256")
) -> bytes:
    body_bytes = await request.body()
    if not verify_github_signature(settings.GITHUB_WEBHOOK_SECRET, body_bytes, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature"
        )
    return body_bytes
