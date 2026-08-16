import logging
from typing import Optional, Dict, Any
import httpx

from ..config import settings

logger = logging.getLogger(__name__)


async def fetch_repository_from_node_graphql(
    node_id: str,
    token: str,
    api_url: str = "https://api.github.com",
    http_client: Optional[httpx.AsyncClient] = None
) -> Optional[str]:
    """
    Consulta o repositório associado a um node (Issue ou PullRequest) no GitHub GraphQL API v4.
    Retorna o nameWithOwner (ex: 'owner/repo') ou None se for DraftIssue ou inválido.
    """
    if not node_id or not token:
        return None

    if api_url.rstrip("/").endswith("/api/v3"):
        graphql_url = f"{api_url.rstrip('/')[:-7]}/api/graphql"
    else:
        graphql_url = f"{api_url.rstrip('/')}/graphql"

    query = """
    query GetRepoFromContentNode($nodeId: ID!) {
      node(id: $nodeId) {
        ... on Issue {
          repository {
            nameWithOwner
          }
        }
        ... on PullRequest {
          repository {
            nameWithOwner
          }
        }
        ... on ProjectV2Item {
          content {
            ... on Issue {
              repository {
                nameWithOwner
              }
            }
            ... on PullRequest {
              repository {
                nameWithOwner
              }
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
            logger.warning(
                "Falha HTTP na consulta GraphQL de repositório (status %s): %s",
                response.status_code,
                response.text
            )
            return None

        data = response.json()
        if "errors" in data and data["errors"]:
            logger.warning("Erros retornados pelo GraphQL de repositório: %s", data["errors"])
            return None

        node_data = (data.get("data") or {}).get("node") or {}
        if not node_data or not isinstance(node_data, dict):
            return None

        # 1. Repositório direto em node.repository (Issue ou PullRequest)
        repo_obj = node_data.get("repository")
        if isinstance(repo_obj, dict):
            name_with_owner = repo_obj.get("nameWithOwner")
            if name_with_owner and isinstance(name_with_owner, str):
                return name_with_owner.strip()

        # 2. Repositório aninhado em node.content.repository (ProjectV2Item)
        content_obj = node_data.get("content")
        if isinstance(content_obj, dict):
            nested_repo = content_obj.get("repository")
            if isinstance(nested_repo, dict):
                nested_name = nested_repo.get("nameWithOwner")
                if nested_name and isinstance(nested_name, str):
                    return nested_name.strip()

        return None
    except Exception as exc:
        logger.warning("Exceção ao consultar repositório via GraphQL: %s", exc)
        return None
    finally:
        if should_close:
            await client.aclose()


async def resolve_repository_from_event(
    event_type: str,
    payload: Dict[str, Any],
    token: Optional[str] = None,
    api_url: Optional[str] = None,
    http_client: Optional[httpx.AsyncClient] = None
) -> Optional[str]:
    """
    Resolve o repositório alvo (formato 'owner/repo') a partir do payload de webhook do GitHub.
    1. Verifica campos nativos do payload (payload.repository.full_name, nameWithOwner, etc.)
    2. Para eventos de projects_v2_item com content_node_id ou node_id, resolve via GraphQL API v4
    3. Se não resolvido, retorna o DEFAULT_GITHUB_REPOSITORY configurado ou None.
    """
    if not isinstance(payload, dict):
        return getattr(settings, "DEFAULT_GITHUB_REPOSITORY", None)

    # 1. Extração de repositório nativo em payload.repository / payload.repo
    raw_repo = payload.get("repository") or payload.get("repo")
    if isinstance(raw_repo, dict):
        full_name = raw_repo.get("full_name") or raw_repo.get("name_with_owner") or raw_repo.get("name")
        if full_name and isinstance(full_name, str) and full_name.strip():
            return full_name.strip()
    elif isinstance(raw_repo, str) and raw_repo.strip():
        return raw_repo.strip()

    # 2. Resolução para projects_v2_item via GraphQL
    pv2 = payload.get("projects_v2_item")
    if isinstance(pv2, dict) or event_type == "projects_v2_item":
        pv2_dict = pv2 if isinstance(pv2, dict) else payload
        content_type = pv2_dict.get("content_type")

        # DraftIssue explicitamente não possui repositório associado
        if content_type != "DraftIssue":
            node_id = pv2_dict.get("content_node_id") or pv2_dict.get("node_id")
            auth_token = token or getattr(settings, "GITHUB_TOKEN", "")
            base_api_url = api_url or getattr(settings, "GITHUB_API_URL", "https://api.github.com")

            if node_id and auth_token:
                resolved_repo = await fetch_repository_from_node_graphql(
                    node_id=node_id,
                    token=auth_token,
                    api_url=base_api_url,
                    http_client=http_client
                )
                if resolved_repo:
                    return resolved_repo

    # 3. Fallback para default repository configurado
    default_repo = getattr(settings, "DEFAULT_GITHUB_REPOSITORY", None)
    if default_repo and isinstance(default_repo, str) and default_repo.strip():
        return default_repo.strip()

    return None
