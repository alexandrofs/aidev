import logging
from typing import Optional, Dict, Any
import httpx

from ..config import settings

logger = logging.getLogger(__name__)


def is_status_ready(status_val: Optional[Any]) -> bool:
    """Verifica se um valor de status/coluna corresponde a 'ready' (case-insensitive)."""
    if not status_val:
        return False
    if isinstance(status_val, str):
        return status_val.strip().lower() == "ready"
    if isinstance(status_val, dict):
        name = status_val.get("name") or status_val.get("value")
        if isinstance(name, str):
            return name.strip().lower() == "ready"
    return False


async def fetch_project_item_status_graphql(
    node_id: str,
    token: str,
    api_url: str = "https://api.github.com",
    http_client: Optional[httpx.AsyncClient] = None
) -> Optional[str]:
    """
    Consulta o status de um ProjectV2Item no GitHub GraphQL API v4.
    Retorna o nome da opção do campo 'Status' (ex: 'Ready', 'Todo', 'Backlog') ou None.
    """
    if not node_id or not token:
        return None

    if api_url.rstrip("/").endswith("/api/v3"):
        graphql_url = f"{api_url.rstrip('/')[:-7]}/api/graphql"
    else:
        graphql_url = f"{api_url.rstrip('/')}/graphql"

    query = """
    query GetProjectItemStatus($nodeId: ID!) {
      node(id: $nodeId) {
        ... on ProjectV2Item {
          fieldValueByName(name: "Status") {
            ... on ProjectV2ItemFieldSingleSelectValue {
              name
            }
          }
        }
      }
    }
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }

    client = http_client or httpx.AsyncClient(timeout=10.0)
    should_close = (client is not http_client)
    try:
        response = await client.post(
            graphql_url,
            headers=headers,
            json={"query": query, "variables": {"nodeId": node_id}}
        )
        if response.is_error:
            logger.warning("Falha HTTP na consulta GraphQL de ProjectV2Item (status %s): %s", response.status_code, response.text)
            return None

        data = response.json()
        if "errors" in data and data["errors"]:
            logger.warning("Erros retornados pelo GraphQL de ProjectV2Item: %s", data["errors"])
            return None

        node_data = data.get("data", {}).get("node", {})
        if not node_data:
            return None

        field_value = node_data.get("fieldValueByName", {})
        if isinstance(field_value, dict):
            return field_value.get("name")
        return None
    except Exception as exc:
        logger.warning("Exceção ao consultar status de ProjectV2Item via GraphQL: %s", exc)
        return None
    finally:
        if should_close:
            await client.aclose()


async def classify_event_status(
    event_type: str,
    payload: Dict[str, Any],
    token: Optional[str] = None,
    api_url: Optional[str] = None,
    http_client: Optional[httpx.AsyncClient] = None
) -> str:
    """
    Avalia a elegibilidade de um evento recebido via webhook.
    Um evento só é elegível (retorna 'PENDING') se estiver em uma coluna 'Ready' de um projeto.
    Caso contrário, retorna 'IGNORED'.
    """
    if not isinstance(payload, dict):
        return "IGNORED"

    # 1. Inspeção direta em payload.status / payload.column / payload.status_name / payload.column_name
    for key in ["status", "column", "status_name", "column_name", "project_status"]:
        val = payload.get(key)
        if val:
            return "PENDING" if is_status_ready(val) else "IGNORED"

    # 2. Inspeção em payload.project_card (Classic Projects)
    if "project_card" in payload and isinstance(payload["project_card"], dict):
        card = payload["project_card"]
        col = card.get("column_name") or card.get("column") or payload.get("column_name")
        if col:
            return "PENDING" if is_status_ready(col) else "IGNORED"

    # 3. Inspeção em payload.changes.field_value (Projects v2 inline)
    changes = payload.get("changes")
    if isinstance(changes, dict) and "field_value" in changes:
        fv = changes["field_value"]
        if isinstance(fv, dict):
            field_name = str(fv.get("field_name") or "").lower()
            if not field_name or field_name == "status":
                to_val = fv.get("to") or fv.get("name") or fv.get("value")
                if to_val:
                    return "PENDING" if is_status_ready(to_val) else "IGNORED"

    # 4. Inspeção direta em payload.projects_v2_item (se possuir campo status/column inline)
    pv2 = payload.get("projects_v2_item")
    if isinstance(pv2, dict):
        for key in ["status", "column", "column_name", "status_name"]:
            val = pv2.get(key)
            if val:
                return "PENDING" if is_status_ready(val) else "IGNORED"

        # 5. Resolução dinâmica via GraphQL para projects_v2_item (ex: action 'reordered' ou 'edited' sem inline)
        node_id = pv2.get("node_id")
        auth_token = token or getattr(settings, "GITHUB_TOKEN", "")
        base_api_url = api_url or getattr(settings, "GITHUB_API_URL", "https://api.github.com")

        if node_id and auth_token:
            status_name = await fetch_project_item_status_graphql(
                node_id=node_id,
                token=auth_token,
                api_url=base_api_url,
                http_client=http_client
            )
            if status_name:
                return "PENDING" if is_status_ready(status_name) else "IGNORED"

    # 6. Flag explícita is_ready no payload (para testes e eventos customizados)
    if payload.get("is_ready") is True:
        return "PENDING"

    # Padrão: se não comprovado que está na coluna Ready de um projeto -> IGNORED
    return "IGNORED"
