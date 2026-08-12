---
baseline_commit: 2744d803d67e38a4c7c1462a1d2cb49407943187
---

# Story 1.2: Endpoint de Recepção, Validação e Ingestão de Webhooks (`ai-dev-api`)

Status: done

## Story

As a sistema AIDEV,
I want um serviço FastAPI (`ai-dev-api`) que receba e valide webhooks assinados do GitHub e persista o payload no PostgreSQL,
so that nenhum evento enviado pelo GitHub (como movimentação para "Ready for AI Dev") seja perdido ou processado sem validação de segurança.

## Acceptance Criteria

1. **Recepção e Autenticação de Webhook do GitHub (AC: 1)**
   - **Given** um evento enviado pelo GitHub via requisição HTTP POST para `/webhooks/github`
   - **When** a requisição contiver o cabeçalho `X-Hub-Signature-256` assinado com o segredo configurado (`GITHUB_WEBHOOK_SECRET`)
   - **Then** a API deve calcular a assinatura HMAC-SHA256 do corpo bruto (raw bytes) e validar contra o valor do cabeçalho
   - **And** se a assinatura for válida, aceitar a requisição para processamento.

2. **Validação de Assinatura Inválida e Rejeição Segura (AC: 2)**
   - **Given** uma requisição para `/webhooks/github` com assinatura ausente, incorreta ou malformatada
   - **When** a validação de segurança for executada
   - **Then** a API deve rejeitar a requisição imediatamente com código HTTP 401 Unauthorized sem realizar nenhuma operação de leitura ou escrita no banco de dados.

3. **Validação de Payload e Estrutura JSON (AC: 3)**
   - **Given** uma requisição POST com assinatura válida mas corpo malformatado (ex: JSON corrompido ou corpo vazio)
   - **When** o parsing do payload for executado
   - **Then** a API deve responder com código HTTP 400 Bad Request detalhando o erro de validação.

4. **Classificação do Evento e Persistência no Event Store (AC: 4)**
   - **Given** uma requisição autenticada e com payload JSON válido
   - **When** a API processar a mensagem
   - **Then** ela deve identificar o `event_type` a partir do cabeçalho `X-GitHub-Event` (ex: `projects_v2_item`, `workflow_run`, `issue_comment`) e o `event_id` a partir do cabeçalho `X-GitHub-Delivery`
   - **And** gravar o registro na tabela `events` do PostgreSQL com `status = 'PENDING'`, `event_id`, `event_type`, `payload` (JSONB) e `retry_count = 0`
   - **And** responder com código HTTP 202 Accepted contendo no corpo a confirmação do evento persistido (`id`, `event_id`, `event_type`, `status`).

5. **Tratamento de Idempotência na Ingestão (AC: 5)**
   - **Given** uma tentativa de reenvio do mesmo evento cujo `event_id` já existe na tabela `events` (restrição UNIQUE `idx_events_event_id`)
   - **When** a API tentar realizar a inserção no PostgreSQL
   - **Then** o sistema deve capturar a violação de chave duplicada (IntegrityError) e responder HTTP 202 Accepted com indicação de evento já registrado, garantindo a idempotência da ingestão sem duplicar registros nem falhar com HTTP 500.

6. **Empacotamento OCI/Docker da API (`ai-dev-api`), Endpoint de Healthcheck e Docker Compose (AC: 6)**
   - **Given** a aplicação FastAPI estruturada no módulo `api/`
   - **When** o comando `docker build` for executado no diretório `api/`
   - **Then** deve ser gerada uma imagem OCI/Docker imutável `ai-dev-api` executando com uvicorn e disponibilizando o endpoint `/healthz` (HTTP 200 OK)
   - **And** o serviço `ai-dev-api` deve ser incluído no `docker-compose.yml` da raiz do projeto, configurado para depender de `ai-dev-migrations` (`service_completed_successfully`).

7. **Suíte de Testes Automatizados da API (AC: 7)**
   - **Given** o componente `ai-dev-api` e seus endpoints
   - **When** a suíte de testes `pytest` for executada em `tests/api/`
   - **Then** os testes automatizados devem cobrir:
     - Endpoint `/healthz` (HTTP 200)
     - Recebimento de webhook com assinatura HMAC válida (HTTP 202 e gravação no DB)
     - Rejeição de webhook sem assinatura ou assinatura inválida (HTTP 401)
     - Rejeição de webhook com payload malformatado (HTTP 400)
     - Ingestão idempotente de `event_id` duplicado (HTTP 202 idempotente).

## Tasks / Subtasks

- [x] Task 1: Estrutura base da aplicação FastAPI e gerenciamento de dependências no módulo `api/` (AC: 6)
  - [x] Criar diretório `api/` com arquivo `pyproject.toml` configurando dependências (`fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `psycopg`, `httpx`, `pytest`, `pytest-asyncio`)
  - [x] Criar `api/src/config.py` para carregar configurações de ambiente via `pydantic-settings` (`GITHUB_WEBHOOK_SECRET`, `DATABASE_URL`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `API_PORT`)
  - [x] Criar `api/src/database.py` fornecendo engine SQLAlchemy assíncrona (`create_async_engine`) e gerenciador de sessão `async_sessionmaker` usando o driver `postgresql+psycopg://`
  - [x] Criar `api/src/main.py` com o aplicativo FastAPI e rota GET `/healthz` retornando `{"status": "ok"}`

- [x] Task 2: Módulo de segurança e validação de assinatura HMAC SHA-256 (AC: 1, 2)
  - [x] Criar `api/src/security.py` com a função `verify_github_signature(secret: str, body: bytes, signature_header: Optional[str]) -> bool` utilizando `hmac` e `hashlib.sha256` com `hmac.compare_digest`
  - [x] Criar dependência FastAPI `validate_github_signature` que lê os bytes brutos do corpo da requisição e valida o cabeçalho `X-Hub-Signature-256`
  - [x] Levantar `HTTPException(status_code=401, detail="Invalid signature")` imediatamente quando a assinatura for ausente ou inválida

- [x] Task 3: Endpoint de ingestão `/webhooks/github` e persistência assíncrona (AC: 1, 3, 4, 5)
  - [x] Criar `api/src/routes/webhooks.py` expondo `POST /webhooks/github` protegido pela dependência de assinatura
  - [x] Extrair o tipo de evento do cabeçalho `X-GitHub-Event` (default `'unknown'` se ausente) e o ID do evento do cabeçalho `X-GitHub-Delivery` (gerar UUID string se ausente)
  - [x] Validar se o corpo é um JSON válido; caso seja inválido ou corrompido, lançar `HTTPException(status_code=400, detail="Invalid JSON payload")`
  - [x] Inserir o registro na tabela `events` com `event_id`, `event_type`, `payload` e `status = 'PENDING'` via `AsyncSession`
  - [x] Capturar `IntegrityError` (violação da constraint UNIQUE em `event_id`) e retornar HTTP 202 Accepted informando que o evento já foi previamente ingerido
  - [x] Retornar HTTP 202 Accepted com os metadados do evento persistido

- [x] Task 4: Dockerfile de `ai-dev-api` e atualização do `docker-compose.yml` (AC: 6)
  - [x] Criar `api/Dockerfile` multi-stage ou slim baseado em `python:3.12-slim` com uvicorn expondo a porta 8000 e healthcheck configurado
  - [x] Atualizar `docker-compose.yml` na raiz adicionando o serviço `ai-dev-api` com mapeamento de porta `8000:8000`, carregando as variáveis de ambiente necessárias e dependendo de `ai-dev-migrations` (`condition: service_completed_successfully`)

- [x] Task 5: Suíte de testes automatizados da API (AC: 7)
  - [x] Criar `tests/api/conftest.py` configurando fixtures de teste assíncronas com `httpx.AsyncClient` e banco PostgreSQL / SQLite em memória ou contêiner de teste
  - [x] Criar `tests/api/test_health.py` testando GET `/healthz`
  - [x] Criar `tests/api/test_webhooks.py` cobrindo envio de webhooks válidos, inválidos (sem/com assinatura errada), payload corrompido e duplicidade de `event_id`

- [x] Task 6: Documentação no `README.md` (AC: 6)
  - [x] Atualizar o `README.md` da raiz descrevendo o serviço `ai-dev-api`, o endpoint `/webhooks/github`, as variáveis de ambiente necessárias (`GITHUB_WEBHOOK_SECRET`), exemplos de `curl` com assinatura simulada e comandos para executar os testes da API

### Review Findings

- [x] [Review][Decision→Patch] Idempotência quebrada para eventos sem `X-GitHub-Delivery` — **Resolvido: rejeitar com HTTP 400.** Implementado em `webhooks.py` com validação explícita e teste `test_webhook_missing_delivery_header`. [api/src/routes/webhooks.py]
- [x] [Review][Dismiss] Double-encoding JSONB: `json.dumps(payload)` passado para campo JSONB — **Falso positivo:** SQLAlchemy `text()` + psycopg3 trata a string JSON corretamente em JSONB sem double-encoding. Mantido `json.dumps` por ser compatível com SQLite (testes) e PostgreSQL (produção). [api/src/routes/webhooks.py]
- [x] [Review][Patch] Secret padrão `default_secret` documentado no README e no docker-compose — **Corrigido:** docker-compose usa `${GITHUB_WEBHOOK_SECRET:?...}` (falha se não definido). README removeu referência ao `default_secret`. [README.md, docker-compose.yml]
- [x] [Review][Patch] Dockerfile roda como root — **Corrigido:** `RUN useradd -m appuser && USER appuser` adicionado antes do CMD. [api/Dockerfile]
- [x] [Review][Patch] Cobertura de testes incompleta: body vazio e assinatura malformatada — **Corrigido:** Adicionados `test_webhook_empty_body`, `test_webhook_malformed_signature_no_prefix` e `test_webhook_missing_delivery_header`. [tests/api/test_webhooks.py]
- [x] [Review][Patch] `asyncio_mode` não configurado no pytest — **Corrigido:** `asyncio_mode = auto` adicionado em `api/pyproject.toml` e `pytest.ini` na raiz do projeto. [api/pyproject.toml, pytest.ini]
- [x] [Review][Defer] Engine SQLAlchemy criado em import-time em `database.py` — O engine singleton é criado no carregamento do módulo, antes de qualquer override de configuração de teste. Pré-existente por design (mitigado pelo override de `get_async_session`), mas pode causar problemas se o engine for referenciado diretamente. Deferido — pre-existing [api/src/database.py]
- [x] [Review][Defer] Status hardcoded `"PENDING"` na resposta de duplicata idempotente — O código retorna `"status": "PENDING"` hardcoded sem consultar o estado real do evento no banco. Pode retornar informação incorreta se o evento já foi processado. Deferido — comportamento dentro do escopo do AC-5, melhoria futura [api/src/routes/webhooks.py]
- [x] [Review][Defer] `db_session` sem rollback explícito entre testes — Fixtures de teste não fazem rollback entre casos, potencial vazamento de estado em suítes expandidas. Deferido — scope function garante DB novo por teste atualmente [tests/api/conftest.py]

## Dev Notes

### Contexto de Arquitetura & Guardrails

- **AD-1 (Persistência de Webhook):** A API `ai-dev-api` é responsável EXCLUSIVAMENTE por receber, autenticar, classificar e persistir eventos de webhook no PostgreSQL com o status inicial `PENDING`. Ela NÃO deve disparar nem executar a lógica de negócios das histórias de usuário.
- **AD-2 (Consumo via PostgreSQL):** O status `PENDING` garante que os workers (`ai-dev-executor` e `ai-dev-notifications`) possam ler e travar os eventos elegíveis posteriormente via `SKIP LOCKED`.
- **AD-3 (Idempotência):** O campo `event_id` mapeado a partir do cabeçalho `X-GitHub-Delivery` possui restrição `UNIQUE` (`idx_events_event_id`). Ao tentar inserir um `event_id` já gravado, a API deve tratar amigavelmente o `IntegrityError` do banco e responder HTTP 202 Accepted sem duplicação de dados.
- **AD-10 (Empacotamento OCI/Docker):** O componente `ai-dev-api` deve ser compilado e entregue como uma imagem Docker isolada e auto-contida.

### Estrutura de Arquivos Recomendada

```text
{project-root}/
  docker-compose.yml            # Atualizado para incluir o serviço ai-dev-api
  README.md                     # Atualizado com documentação dos endpoints da API
  api/
    Dockerfile                  # Imagem OCI para ai-dev-api
    pyproject.toml              # Dependências do serviço API (FastAPI, uvicorn, pydantic, sqlalchemy, etc.)
    src/
      __init__.py
      config.py                 # Leitura de variáveis de ambiente (DB + GITHUB_WEBHOOK_SECRET)
      database.py               # Gerenciador de sessão assíncrona SQLAlchemy (AsyncSession)
      main.py                   # Instância FastAPI, middlewares e inclusão de roteadores
      security.py               # Função e dependência de verificação HMAC-SHA256
      routes/
        __init__.py
        webhooks.py             # Endpoint POST /webhooks/github
  tests/
    api/
      __init__.py
      conftest.py               # Fixtures de teste para a API
      test_health.py            # Testes do endpoint /healthz
      test_webhooks.py          # Testes de integração do endpoint /webhooks/github
```

### Exemplo de Verificação HMAC em Python (`security.py`)

```python
import hmac
import hashlib
from typing import Optional

def verify_github_signature(secret: str, body: bytes, signature_header: Optional[str]) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature_header)
```

### Padrão de Inserção Idempotente no PostgreSQL (`routes/webhooks.py`)

```python
from fastapi import APIRouter, Request, Header, HTTPException, status, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import json
import uuid

router = APIRouter()

@router.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED)
async def receive_github_webhook(
    request: Request,
    x_github_event: str = Header(default="unknown"),
    x_github_delivery: str = Header(default_factory=lambda: str(uuid.uuid4())),
    session: AsyncSession = Depends(get_async_session)
):
    body_bytes = await request.body()
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    try:
        stmt = text("""
            INSERT INTO events (event_id, event_type, status, payload, retry_count)
            VALUES (:event_id, :event_type, 'PENDING', :payload, 0)
            RETURNING id, event_id, event_type, status, created_at
        """)
        result = await session.execute(stmt, {
            "event_id": x_github_delivery,
            "event_type": x_github_event,
            "payload": json.dumps(payload)
        })
        await session.commit()
        row = result.fetchone()
        return {
            "message": "Event received and persisted",
            "event_id": row.event_id,
            "event_type": row.event_type,
            "status": row.status
        }
    except IntegrityError:
        await session.rollback()
        return {
            "message": "Event already processed (idempotent duplicate)",
            "event_id": x_github_delivery,
            "event_type": x_github_event,
            "status": "PENDING"
        }
```

### Previous Story Intelligence (`1-1-schema-do-event-store-e-migracoes-em-postgresql-ai-dev-migrations`)

- **Conexão com PostgreSQL via Psycopg3:** O driver de banco configurado na História 1.1 utiliza `postgresql+psycopg://`. A API `ai-dev-api` deve utilizar o mesmo driver assíncrono para garantir compatibilidade com `DatabaseSettings`.
- **Esquema da Tabela `events`:** A coluna `event_id` tem restrição `UNIQUE` e o campo `status` tem valor default `'PENDING'`. A coluna `payload` armazena dados em `JSONB`.
- **Docker Compose Healthcheck:** O serviço `ai-dev-api` deve aguardar `ai-dev-migrations` terminar com sucesso usando `condition: service_completed_successfully`.

### References

- [ARCHITECTURE-SPINE.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/architecture/architecture-AI%20Developer-2026-08-09/ARCHITECTURE-SPINE.md#L38-L87) - Decisões de Arquitetura AD-1, AD-2, AD-3 e AD-10
- [epics.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/epics.md#L115-L126) - Requisitos e Critérios de Aceite da Story 1.2
- [1-1-schema-do-event-store-e-migracoes-em-postgresql-ai-dev-migrations.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/implementation-artifacts/1-1-schema-do-event-store-e-migracoes-em-postgresql-ai-dev-migrations.md) - Esquema e histórico da história anterior

## Dev Agent Record

### Agent Model Used

Gemini 3.6 Flash (High)

### Debug Log References

- All 6 API tests (`tests/api/test_health.py` and `tests/api/test_webhooks.py`) passed 100%.

### Completion Notes List

- Story context created for 1.2 Webhook Ingestion API (`ai-dev-api`)
- Implemented FastAPI service `ai-dev-api` with `/healthz` and `/webhooks/github` endpoints.
- Implemented HMAC SHA-256 signature verification (`X-Hub-Signature-256`) returning HTTP 401 on invalid/missing signatures.
- Implemented JSON payload parsing returning HTTP 400 on malformed payloads.
- Implemented async PostgreSQL event persistence with `status = 'PENDING'`, `event_id`, `event_type`, and `payload`.
- Implemented idempotent duplicate ingestion handling returning HTTP 202 on duplicate `event_id`.
- Packaged OCI Docker image (`api/Dockerfile`) and integrated `ai-dev-api` into `docker-compose.yml`.
- Authored comprehensive test suite in `tests/api/`.

### File List

- `api/pyproject.toml`
- `api/Dockerfile`
- `api/src/__init__.py`
- `api/src/config.py`
- `api/src/database.py`
- `api/src/main.py`
- `api/src/security.py`
- `api/src/routes/__init__.py`
- `api/src/routes/webhooks.py`
- `docker-compose.yml`
- `README.md`
- `tests/api/__init__.py`
- `tests/api/conftest.py`
- `tests/api/test_health.py`
- `tests/api/test_webhooks.py`
- `_bmad-output/implementation-artifacts/1-2-endpoint-de-recepcao-validacao-e-ingestao-de-webhooks-ai-dev-api.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

### Change Log

- Created story specification document for Story 1.2 (Date: 2026-08-12)
- Implemented `ai-dev-api` FastAPI application, signature validation, ingestion route, Dockerfile, docker-compose service, unit tests, and README documentation (Date: 2026-08-12)

