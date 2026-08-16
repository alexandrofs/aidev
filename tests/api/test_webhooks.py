import json
from unittest.mock import patch, AsyncMock
import pytest
from sqlalchemy import text


async def test_webhook_valid_signature_and_persistence(async_client, db_session, make_signature):
    payload = {"action": "edited", "issue": {"number": 42}, "status": "Ready"}
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
    payload = {"action": "opened", "status": "Ready"}
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    shared_delivery = "delivery-duplicate-uuid-999"

    # First request
    res1 = await async_client.post(
        "/webhooks/github",
        content=body_bytes,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": shared_delivery,
        }
    )
    assert res1.status_code == 202
    assert res1.json()["message"] == "Event received and persisted"
    assert res1.json()["status"] == "PENDING"

    # Second duplicate request
    res2 = await async_client.post(
        "/webhooks/github",
        content=body_bytes,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": shared_delivery,
        }
    )
    assert res2.status_code == 202
    assert res2.json()["message"] == "Event already processed (idempotent duplicate)"
    assert res2.json()["event_id"] == "delivery-duplicate-uuid-999"
    assert res2.json()["status"] == "PENDING"


async def test_webhook_event_type_projects_v2_item_ready(async_client, db_session, make_signature):
    """[P1] Aceita evento projects_v2_item com status Ready e persiste como PENDING."""
    payload = {
        "action": "edited",
        "changes": {
            "field_value": {
                "field_name": "Status",
                "to": {"name": "Ready"}
            }
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "projects_v2_item",
        "X-GitHub-Delivery": "delivery-projects-v2-item-ready-001",
        "Content-Type": "application/json",
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 202
    data = response.json()
    assert data["event_type"] == "projects_v2_item"
    assert data["status"] == "PENDING"

    result = await db_session.execute(
        text("SELECT event_type, status FROM events WHERE event_id = :event_id"),
        {"event_id": "delivery-projects-v2-item-ready-001"},
    )
    row = result.fetchone()
    assert row is not None
    assert row.event_type == "projects_v2_item"
    assert row.status == "PENDING"


async def test_webhook_event_type_projects_v2_item_ignored(async_client, db_session, make_signature):
    """[P1] Evento projects_v2_item com status Todo é persistido como IGNORED."""
    payload = {
        "action": "edited",
        "changes": {
            "field_value": {
                "field_name": "Status",
                "to": {"name": "Todo"}
            }
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "projects_v2_item",
        "X-GitHub-Delivery": "delivery-projects-v2-item-ignored-001",
        "Content-Type": "application/json",
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 202
    data = response.json()
    assert data["event_type"] == "projects_v2_item"
    assert data["status"] == "IGNORED"

    result = await db_session.execute(
        text("SELECT event_type, status FROM events WHERE event_id = :event_id"),
        {"event_id": "delivery-projects-v2-item-ignored-001"},
    )
    row = result.fetchone()
    assert row is not None
    assert row.status == "IGNORED"


async def test_webhook_projects_v2_item_reordered_graphql_ready(async_client, db_session, make_signature):
    """[P1] Evento projects_v2_item reordered resolve status Ready via GraphQL e persiste como PENDING."""
    payload = {
        "action": "reordered",
        "projects_v2_item": {
            "id": 229641266,
            "node_id": "PVTI_lADOEu2-uM4Bgi4wzg2wDDI",
            "project_node_id": "PVT_kwDOEu2-uM4Bgi4w",
            "content_node_id": "I_kwDOMrPR8s8AAAABM_ECQA",
            "content_type": "Issue"
        },
        "changes": {
            "previous_projects_v2_item_node_id": {"from": None, "to": None}
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "projects_v2_item",
        "X-GitHub-Delivery": "delivery-pv2-reordered-ready-001",
        "Content-Type": "application/json",
    }

    with patch("src.services.triage.fetch_project_item_status_graphql", new=AsyncMock(return_value="Ready")):
        with patch("src.services.triage.settings.GITHUB_TOKEN", "mock-token"):
            response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
            assert response.status_code == 202
            data = response.json()
            assert data["status"] == "PENDING"


async def test_webhook_projects_v2_item_reordered_graphql_not_ready(async_client, db_session, make_signature):
    """[P1] Evento projects_v2_item reordered resolve status In Progress via GraphQL e persiste como IGNORED."""
    payload = {
        "action": "reordered",
        "projects_v2_item": {
            "id": 229641266,
            "node_id": "PVTI_lADOEu2-uM4Bgi4wzg2wDDI",
            "project_node_id": "PVT_kwDOEu2-uM4Bgi4w",
            "content_node_id": "I_kwDOMrPR8s8AAAABM_ECQA",
            "content_type": "Issue"
        },
        "changes": {
            "previous_projects_v2_item_node_id": {"from": None, "to": None}
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "projects_v2_item",
        "X-GitHub-Delivery": "delivery-pv2-reordered-inprogress-001",
        "Content-Type": "application/json",
    }

    with patch("src.services.triage.fetch_project_item_status_graphql", new=AsyncMock(return_value="In Progress")):
        with patch("src.services.triage.settings.GITHUB_TOKEN", "mock-token"):
            response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
            assert response.status_code == 202
            data = response.json()
            assert data["status"] == "IGNORED"


async def test_webhook_project_card_ready(async_client, db_session, make_signature):
    """[P1] Evento project_card com column_name Ready persiste como PENDING."""
    payload = {
        "action": "moved",
        "project_card": {
            "id": 123,
            "column_name": "Ready"
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "project_card",
        "X-GitHub-Delivery": "delivery-project-card-ready-001",
        "Content-Type": "application/json",
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "PENDING"


async def test_webhook_project_card_ignored(async_client, db_session, make_signature):
    """[P1] Evento project_card com column_name Backlog persiste como IGNORED."""
    payload = {
        "action": "moved",
        "project_card": {
            "id": 124,
            "column_name": "Backlog"
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "project_card",
        "X-GitHub-Delivery": "delivery-project-card-ignored-001",
        "Content-Type": "application/json",
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "IGNORED"


async def test_webhook_event_type_workflow_run_ignored_when_not_ready(async_client, db_session, make_signature):
    """[P1] Evento workflow_run sem flag Ready persiste como IGNORED."""
    body_bytes = b'{"action": "completed", "workflow_run": {"id": 99}}'
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "workflow_run",
        "X-GitHub-Delivery": "delivery-workflow-run-001",
        "Content-Type": "application/json",
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 202
    data = response.json()
    assert data["event_type"] == "workflow_run"
    assert data["status"] == "IGNORED"


async def test_webhook_event_type_workflow_run_pending_when_ready(async_client, db_session, make_signature):
    """[P1] Evento workflow_run com status Ready persiste como PENDING."""
    body_bytes = b'{"action": "completed", "status": "Ready", "workflow_run": {"id": 99}}'
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "workflow_run",
        "X-GitHub-Delivery": "delivery-workflow-run-ready-001",
        "Content-Type": "application/json",
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 202
    data = response.json()
    assert data["event_type"] == "workflow_run"
    assert data["status"] == "PENDING"


async def test_webhook_default_event_type_when_header_absent(async_client, db_session, make_signature):
    """[P1] Quando X-GitHub-Event ausente, event_type deve ser 'unknown' e status 'IGNORED'."""
    body_bytes = b'{"action": "ping"}'
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Delivery": "delivery-no-event-header-001",
        "Content-Type": "application/json",
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 202
    data = response.json()
    assert data["event_type"] == "unknown"
    assert data["status"] == "IGNORED"


async def test_webhook_response_includes_id_field(async_client, db_session, make_signature):
    """[P1] A resposta de persistência bem-sucedida deve incluir o campo 'id'."""
    payload = {"action": "labeled", "label": {"name": "AI Dev"}, "status": "Ready"}
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": "delivery-id-field-check-001",
        "Content-Type": "application/json",
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 202
    data = response.json()
    assert "id" in data
    assert data["id"] is not None


async def test_webhook_idempotency_determined_by_event_id_not_event_type(
    async_client, db_session, make_signature
):
    """[P1] Idempotência baseia-se apenas em event_id; event_type diferente não importa."""
    payload = {"action": "opened", "status": "Ready"}
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    shared_delivery = "delivery-same-id-diff-type-999"

    # Primeiro envio com event_type "issues"
    res1 = await async_client.post(
        "/webhooks/github",
        content=body_bytes,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": shared_delivery,
        },
    )
    assert res1.status_code == 202
    assert res1.json()["message"] == "Event received and persisted"

    # Segundo envio com o MESMO event_id mas event_type diferente
    res2 = await async_client.post(
        "/webhooks/github",
        content=body_bytes,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": shared_delivery,
        },
    )
    assert res2.status_code == 202
    assert res2.json()["message"] == "Event already processed (idempotent duplicate)"


async def test_webhook_issue_comment_event(async_client, db_session, make_signature):
    """[P1] Evento issue_comment sem Ready é aceito e persistido como IGNORED."""
    payload = {"action": "created", "comment": {"body": "LGTM"}}
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = make_signature(body_bytes)

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "issue_comment",
        "X-GitHub-Delivery": "delivery-issue-comment-001",
        "Content-Type": "application/json",
    }

    response = await async_client.post("/webhooks/github", content=body_bytes, headers=headers)
    assert response.status_code == 202
    data = response.json()
    assert data["event_type"] == "issue_comment"
    assert data["status"] == "IGNORED"


async def test_healthz_returns_ok_structure(async_client):
    """[P0] /healthz retorna status 200 com body exato {'status': 'ok'}."""
    response = await async_client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok"}
    assert list(body.keys()) == ["status"]


async def test_healthz_ignores_content_type(async_client):
    """[P2] /healthz responde independente do Content-Type da requisição."""
    response = await async_client.get(
        "/healthz", headers={"Content-Type": "application/xml"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
