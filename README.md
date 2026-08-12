# AI Developer (AIDEV)

## Visão Geral do Projeto

O **AI Developer** é um agente autônomo e resiliente de engenharia de software projetado para interagir diretamente com repositórios GitHub, interpretar eventos/webhooks, processar demandas em um pipeline estruturado e submeter Pull Requests validados.

O projeto adota uma **arquitetura orientada a eventos** com persistência relacional no PostgreSQL, operando em modelo *Event Store* onde todo evento recebido (via webhook) é gravado imutavelmente antes do processamento assíncrono por trabalhadores descentralizados.

## Arquitetura e Componentes Principais

1. **`ai-dev-api`**: FastAPI HTTP gateway responsável por receber, autenticar e validar webhooks do GitHub, inserindo eventos brutos na tabela `events` com status `PENDING`.
2. **`ai-dev-executor`**: Worker de orquestração que consome eventos `PENDING` utilizando a cláusula `FOR UPDATE SKIP LOCKED` do PostgreSQL, executando o agente em ambientes de execução isolados e seguros.
3. **`ai-dev-notifications`**: Worker de notificação que consome eventos de notificação e interage via canais externos (ex: Telegram, alertas HITL).
4. **`ai-dev-migrations`**: Utilitário imutável empacotado em Docker (Python + Alembic) responsável por gerenciar e aplicar o esquema do banco de dados relacional e controle de versão das migrações.

## Esquema do Banco de Dados (`persistence`)

O banco de dados relacional (PostgreSQL 16) possui 3 tabelas fundamentais:

* **`events`**: Event Store principal com suporte a consumo concorrente e garantias de idempotência:
  * `id` (UUID PK)
  * `event_id` (VARCHAR UNIQUE - garante a idempotência dos webhooks do GitHub)
  * `event_type` (VARCHAR)
  * `status` (VARCHAR, default `'PENDING'`)
  * `payload` (JSONB)
  * `retry_count` (INTEGER, default 0)
  * `created_at` e `updated_at` (TIMESTAMPTZ)
  * **Índices otimizados**: `idx_events_status_type` `(status, event_type)` para buscas ultrarrápidas com `FOR UPDATE SKIP LOCKED` e `idx_events_event_id` `(event_id)` para unicidade.
* **`agent_memory`**: Memória hierárquica para contexto contínuo dos agentes (níveis 2 e 3):
  * `id` (UUID PK), `story_id`, `memory_type` (`daily_summary`, `decision`, `long_term`), `content` (JSONB), `created_at`, `updated_at`.
  * **Índice**: `idx_agent_memory_story_type` `(story_id, memory_type)`.
* **`audit_logs`**: Trilha auditável completa de ações e mutações realizadas no sistema (NFR2):
  * `id` (UUID PK), `event_id`, `action`, `actor`, `details` (JSONB), `created_at`.
  * **Índice**: `idx_audit_logs_event_id` `(event_id)`.

---

## Como Rodar Localmente com Docker Compose

### Requisitos Prévios
* Docker Engine / Docker Desktop (com suporte a Docker Compose v2)
* Python 3.9+ (opcional para testes unitários locais)

### Subindo a Infraestrutura e Aplicando Migrações

Para compilar e inicializar o PostgreSQL 16 juntamente com o executor de migrações `ai-dev-migrations`:

```bash
docker compose up --build
```

O container `ai-dev-migrations` aguardará a prontidão de conexões do PostgreSQL via *healthcheck*, executará as migrações via Alembic e encerrará automaticamente com `exit code 0`.

### Verificando os Containers

```bash
docker compose ps
```

---

## Como Executar as Migrações Manualmente

Caso deseje rodar o Alembic diretamente sem o Docker Compose:

1. Ative o ambiente virtual Python e instale as dependências:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e "./persistence[dev]"
   ```

2. Configure as variáveis de ambiente necessárias ou utilize os padrões locais (`localhost:5432`):
   ```bash
   export POSTGRES_HOST=localhost
   export POSTGRES_PORT=5432
   export POSTGRES_DB=aidev
   export POSTGRES_USER=aidev
   export POSTGRES_PASSWORD=aidev
   ```

3. Execute a migração usando o Alembic:
   ```bash
   cd persistence
   alembic upgrade head
   ```

---

---

## Serviço HTTP Gateway (`ai-dev-api`)

O componente `ai-dev-api` expõe a interface HTTP em FastAPI para recebimento e ingestão segura de webhooks do GitHub.

### Endpoints Disponíveis

* **`GET /healthz`**: Verificação de saúde do container (retorna HTTP 200 `{"status": "ok"}`).
* **`POST /webhooks/github`**: Recepção, autenticação HMAC-SHA256 e persistência de eventos de webhook (retorna HTTP 202 Accepted).

### Variáveis de Ambiente

| Variável | Padrão | Descrição |
| :--- | :--- | :--- |
| `GITHUB_WEBHOOK_SECRET` | **obrigatório** | Segredo compartilhado para validação HMAC SHA-256 do GitHub (`X-Hub-Signature-256`). **Nunca deixe vazio em produção.** |
| `POSTGRES_HOST` | `localhost` | Host do banco PostgreSQL |
| `POSTGRES_PORT` | `5432` | Porta do banco PostgreSQL |
| `POSTGRES_DB` | `aidev` | Nome do banco de dados |
| `POSTGRES_USER` | `aidev` | Usuário do PostgreSQL |
| `POSTGRES_PASSWORD` | `aidev` | Senha do PostgreSQL |
| `API_PORT` | `8000` | Porta onde o servidor uvicorn roda |

### Exemplo de Envio de Webhook via `curl`

Para simular o disparo de um webhook assinado via `curl`:

```bash
# 1. Defina o segredo (deve ser o mesmo configurado em GITHUB_WEBHOOK_SECRET) e o payload JSON
SECRET="$GITHUB_WEBHOOK_SECRET"
PAYLOAD='{"action":"labeled","label":{"name":"Ready for AI Dev"}}'

# 2. Calcule a assinatura HMAC SHA-256
SIG=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

# 3. Envie a requisição para a API
curl -X POST http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=$SIG" \
  -H "X-GitHub-Event: projects_v2_item" \
  -H "X-GitHub-Delivery: 72cb0b04-4b32-4720-9a4f-a7e86e17d91e" \
  -d "$PAYLOAD"
```

---

## Suíte de Testes Automatizados

Os testes automatizados verificam o esquema de banco de dados e os contratos da API `ai-dev-api`.

### Executando os Testes da API:

```bash
source .venv/bin/activate
pip install -e "./api[dev]"
pytest tests/api/
```

### Executando Todos os Testes:

```bash
pytest tests/api/ tests/persistence/test_offline_migrations.py
```

