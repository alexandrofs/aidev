import json
import pytest
from sqlalchemy import text


async def test_webhook_valid_signature_and_persistence(async_client, db_session, make_signature):
    payload = {"action": "edited", "issue": {"number": 42}}
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": "delivery-uuid-12345",
        "Content-Type": "application/json"
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 202
    data = response.json()
    assert data["message"] == "Event received and persisted"
    assert data["event_id"] == "delivery-uuid-12345"
    assert data["event_type"] == "issues"
    assert data["status"] == "PENDING"

    # Verify persistence in DB
    result = await db_session.execute(
        text("SELECT event_id, event_type, status, payload FROM events WHERE event_id = :event_id"),
        {"event_id": "delivery-uuid-12345"}
    )
    row = result.fetchone()
    assert row is not None
    assert row.event_id == "delivery-uuid-12345"
    assert row.event_type == "issues"
    assert row.status == "PENDING"
    assert json.loads(row.payload) == payload


async def test_webhook_missing_signature(async_client):
    body_bytes = b'{"action": "test"}'
    headers = {
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": "delivery-uuid-missing-sig"
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid signature"


async def test_webhook_invalid_signature(async_client):
    body_bytes = b'{"action": "test"}'
    headers = {
        "X-Hub-Signature-256": "sha256=invalid1234567890abcdef",
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": "delivery-uuid-invalid-sig"
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid signature"


async def test_webhook_malformed_signature_no_prefix(async_client):
    """Assinatura sem prefixo sha256= deve ser rejeitada com HTTP 401."""
    body_bytes = b'{"action": "test"}'
    headers = {
        "X-Hub-Signature-256": "invalidformat_without_sha256_prefix",
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": "delivery-uuid-bad-prefix"
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid signature"


async def test_webhook_malformed_json_payload(async_client, make_signature):
    body_bytes = b'{"action": "invalid json ...'
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": "delivery-uuid-malformed"
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON payload"


async def test_webhook_empty_body(async_client, make_signature):
    """Body completamente vazio deve retornar HTTP 400 por falha no parsing JSON."""
    body_bytes = b""
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": "delivery-uuid-empty-body"
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON payload"


async def test_webhook_missing_delivery_header(async_client, make_signature):
    """Ausencia do header X-GitHub-Delivery deve retornar HTTP 400."""
    payload = {"action": "test"}
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "issues",
        "Content-Type": "application/json"
        # Sem X-GitHub-Delivery
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 400
    assert "X-GitHub-Delivery" in response.json()["detail"]


async def test_webhook_idempotent_ingestion(async_client, db_session, make_signature):
    payload = {"action": "opened"}
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "delivery-duplicate-uuid-999"
    }

    # First request
    res1 = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert res1.status_code == 202
    assert res1.json()["message"] == "Event received and persisted"

    # Second duplicate request
    res2 = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert res2.status_code == 202
    assert res2.json()["message"] == "Event already processed (idempotent duplicate)"
    assert res2.json()["event_id"] == "delivery-duplicate-uuid-999"
