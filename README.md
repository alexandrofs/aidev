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

## Módulo de Persistência e Consumo Idempotente (`persistence`)

O módulo `persistence` expõe a abstração `EventRepository` para consumo de eventos sem a necessidade de brokers externos de mensageria (AD-2).

### Trava Atômica (`FOR UPDATE SKIP LOCKED`) e Transições de Estado

Workers como `ai-dev-executor` e `ai-dev-notifications` utilizam a classe `EventRepository` para reivindicar eventos em status `PENDING`:

```python
from persistence.src import EventRepository, compute_payload_hash

async with async_session_factory() as session:
    repo = EventRepository(session)
    event = await repo.claim_event(event_types=["push", "issues"], worker_id="executor-worker-1")
    if event:
        # Processa o evento...
        await repo.complete_event(event.event_id, worker_id="executor-worker-1", details={"result": "success"})
    else:
        # Se ocorrer falha:
        await repo.fail_event(event.event_id, worker_id="executor-worker-1", error_message="Connection timeout", max_retries=3)
```

* **Atomicidade (`claim_event`)**: Em PostgreSQL 16, a seleção de eventos executa a cláusula `FOR UPDATE SKIP LOCKED` em uma CTE SQL atômica, alterando o status para `'PROCESSING'` e gravando ação `'CLAIMED'` em `audit_logs`. Em dialetos sem suporte a `SKIP LOCKED` (ex: SQLite em testes unitários), executa fallback gracioso.
* **Garantia de Idempotência (`check_idempotency`)**: Permite verificar duplicatas antes da execução de efeitos colaterais através de `event_id` ou do hash canônico SHA-256 do payload (`compute_payload_hash`).
* **Ciclo de Vida e Auditoria**: Suporta transições para `'COMPLETED'` ou `'FAILED'` (incrementando `retry_count` e re-fileirando para `'PENDING'` se `retry_count < max_retries`). Todas as ações alimentam a tabela `audit_logs`.

---

## Worker Executor e Sandbox Efêmero Docker (`ai-dev-executor`)

O `ai-dev-executor` é o worker em Python 3.12 responsável por consumir eventos elegíveis (`workflow.execution`) do PostgreSQL via `EventRepository.claim_event` e instanciar um container Docker efêmero isolado para cada job de execução de código, testes ou automação (AD-6).

### Orquestração e Teardown Completo do Sandbox (`DockerSandboxManager`)

* **Isolamento de Host (AD-6)**: Cada execução roda dentro de um container Docker efêmero (ex: `python:3.12-slim`) com volumes efêmeros criados em diretórios temporários no host (`mkdtemp`).
* **Garantia de Zero Leakage**: Ao finalizar o job (seja com sucesso, erro ou exceção), o orquestrador obrigatoriamente executa no bloco `finally:` o encerramento gracioso do container (`container.stop()`), a remoção forçada de volumes/containers (`container.remove(v=True, force=True)`) e a deleção dos arquivos temporários do host.
* **Polling com Backoff & Shutdown Gracioso**: O worker opera em loop assíncrono continuo aplicando *exponential backoff* configurável em períodos de ociosidade, e intercepta sinais `SIGTERM`/`SIGINT` para finalizar a execução atual antes do encerramento.

### Variáveis de Ambiente do Executor

| Variável | Padrão | Descrição |
| :--- | :--- | :--- |
| `SANDBOX_IMAGE` | `python:3.12-slim` | Imagem base padrão dos containers de sandbox efêmero |
| `POLL_INTERVAL` | `2.0` | Intervalo inicial de polling em segundos |
| `MAX_POLL_INTERVAL` | `30.0` | Limite máximo do backoff durante ociosidade (segundos) |
| `CONTAINER_TIMEOUT` | `300` | Timeout de execução do container sandbox (segundos) |
| `DOCKER_SOCKET` | `unix:///var/run/docker.sock` | Caminho para comunicação com o Docker daemon |
| `WORKER_ID` | `executor-worker-<hash>` | Identificador único do trabalhador para auditoria e trava de banco |
| `POSTGRES_HOST` | `localhost` | Host do banco PostgreSQL |
| `POSTGRES_PORT` | `5432` | Porta do banco PostgreSQL |
| `POSTGRES_DB` | `aidev` | Nome do banco de dados |
| `POSTGRES_USER` | `aidev` | Usuário do PostgreSQL |
| `POSTGRES_PASSWORD` | `aidev` | Senha do PostgreSQL |
| `OPENROUTER_API_KEY` | `opcional` | Chave de API do OpenRouter para o OpenCode no Sandbox |
| `OPENCODE_MODEL` | `opcional` | Modelo padrão de IA (ex: `openrouter/anthropic/claude-3.5-sonnet`) |

---

## Manifesto do Repositório Alvo (`.aidev.yaml`)

Em arquiteturas multi-repositório, a plataforma `aidev` é totalmente **agnóstica**. Cada **repositório alvo** contém seu próprio arquivo `.aidev.yaml` (ou `.aidev.json`) na raiz para definir suas regras de automação e vinculação:

```yaml
# .aidev.yaml (na raiz do repositório alvo)
version: "1"

github:
  repository: "org/meu-projeto"
  project_number: 1                  # Número do GitHub Projects v2
  project_id: "PVT_kwDO..."           # ID GraphQL do Project v2 (opcional)
  base_branch: "main"
  ready_label: "Ready for AI Dev"
  review_label: "In Review"

workflow:
  phases:
    - "coding"                       # OpenCode executa bmad-dev-story (TDD/testes nativos do projeto)
    - "review"                       # OpenCode executa bmad-code-review (auto-auditoria de qualidade)
```

> **Agnosticismo de Validação**: A validação de código, testes unitários e cobertura de critérios de aceite são de responsabilidade do próprio **harness do agente** (durante as fases de desenvolvimento e revisão). A plataforma `aidev` orquestra o ciclo contínuo e realiza a entrega quando o agente finaliza com sucesso.

### Precedência de Resolução de Configurações
1. **Payload do Evento Webhook** *(maior precedência)*
2. **Manifesto `.aidev.yaml` do Repositório Alvo** *(específico do projeto)*
3. **Variáveis de Ambiente / `.env` da Plataforma** *(fallback global)*

### Integração BMAD no Repositório Alvo (Opcional)

Caso o repositório alvo utilize o framework **BMAD** para geração de histórias e queira automatizar a abertura de Issues padronizadas no GitHub, adicione o arquivo `_bmad/custom/bmad-create-story.toml` no **repositório alvo**:

```toml
# _bmad/custom/bmad-create-story.toml (no repositório alvo)
[workflow]
persistent_facts = [
  "PADRÃO DETERMINÍSTICO DE HISTÓRIAS: Toda história gerada deve ter seu identificador canônico no formato '{epic_num}.{story_num}' (ex: '1.4') e sua chave de arquivo no formato '{epic_num}-{story_num}-{slug}' (ex: '1-4-adicao-da-coluna-repository-no-event-store').",
  "PADRÃO DETERMINÍSTICO DE ISSUES GITHUB: Toda issue associada à história deve conter no cabeçalho os metadados: Story ID, Story Key e o caminho exato do arquivo de especificação em '_bmad-output/implementation-artifacts/{story_key}.md'."
]

on_complete = "Após salvar o arquivo da história e atualizar o sprint-status.yaml, verificar as configurações do repositório alvo (.aidev.yaml se existir) e criar a Issue correspondente no GitHub com a label 'Ready for AI Dev', título padronizado 'feat(story-{{epic_num}}.{{story_num}}): {{story_title}}' e corpo com o link explícito para '_bmad-output/implementation-artifacts/{{story_key}}.md'."
```


---

## Suíte de Testes Automatizados

Os testes automatizados verificam o esquema de banco de dados, o repositório de eventos (concorrência e idempotência), os contratos da API `ai-dev-api` e a orquestração do sandbox efêmero no `ai-dev-executor`.

### Executando os Testes do Executor (`ai-dev-executor`):

```bash
source .venv/bin/activate
pip install -e "./executor[dev]"
pytest tests/executor/
```

### Executando os Testes da API:

```bash
source .venv/bin/activate
pip install -e "./api[dev]"
pytest tests/api/
```

### Executando os Testes de Persistência, Concorrência e Idempotência:

```bash
source .venv/bin/activate
pytest tests/persistence/test_event_consumption.py
```

### Executando Todos os Testes do Projeto:

```bash
pytest
```


