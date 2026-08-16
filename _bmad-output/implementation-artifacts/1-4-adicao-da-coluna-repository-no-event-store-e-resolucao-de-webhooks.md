---
baseline_commit: 0539d46777bc89d8fb28ef94a0889ec172c7a52f
---

# Story 1.4: Adição da Coluna Repository no Event Store e Resolução de Webhooks

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a sistema AIDEV,
I want que a tabela de eventos do PostgreSQL possua uma coluna dedicada `repository`, que o endpoint de webhooks resolva o repositório alvo (inclusive consultando o GitHub GraphQL para eventos de Projects v2) antes de persistir o evento, que a triagem suporte webhooks do tipo `issues` com ação `"action": "labeled"` como `PENDING`, e que o worker extraia o código da história da descrição da issue para criar branches no padrão `feature/<codigo_historia>`,
so that todos os eventos no Event Store possuam um repositório alvo válido e garantido, viabilizando consumo multi-repo, automação direta via issues com labels e branches padronizadas sem dependência de nomes arbitrários.

## Acceptance Criteria

1. **Migração Alembic 005: Adição da Coluna `repository` no Event Store (AC: 1)**
   - **Given** a base de dados PostgreSQL existente com a tabela `events` (após a migração `004_add_error_log_to_events.py`)
   - **When** a migração `005_add_repository_column_to_events.py` do Alembic for aplicada
   - **Then** a coluna `repository VARCHAR(255) NULL` deve ser adicionada à tabela `events`
   - **And** os índices `idx_events_repository` em `('repository')` e `idx_events_repository_status` em `('repository', 'status')` devem ser criados
   - **And** o downgrade da migração deve remover os índices e a coluna de forma idempotente e reversível.

2. **Resolução de Repositório para Webhooks Nativos de Repositório (AC: 2)**
   - **Given** um webhook com payload JSON contendo o objeto de repositório (ex: `payload.repository.full_name`, `payload.repository.name_with_owner` ou `payload.repository` como string)
   - **When** o endpoint `POST /webhooks/github` processar a requisição
   - **Then** o valor de `repository` deve ser extraído diretamente do payload (formato `owner/repo`) e persistido na coluna `repository` da tabela `events`
   - **And** a resposta HTTP 202 Accepted deve incluir o campo `"repository": "<owner/repo>"`.

3. **Resolução Dinâmica de Repositório para Itens de GitHub Projects v2 (`projects_v2_item`) via GraphQL API (AC: 3)**
   - **Given** um webhook `projects_v2_item` onde o repositório não venha explícito no payload raiz e contenha `content_node_id` ou `node_id` associado a uma `Issue` ou `PullRequest`
   - **When** o webhook for recebido em `POST /webhooks/github`
   - **Then** a API deve realizar uma consulta GraphQL (`node(id: $node_id) { ... on Issue { repository { nameWithOwner } } ... on PullRequest { repository { nameWithOwner } } }`) usando o `GITHUB_TOKEN` configurado
   - **And** extrair o repositório (`nameWithOwner`, ex: `owner/repo`) e persistir o registro com `repository = nameWithOwner`.

4. **Validação e Rejeição de Eventos sem Resolução de Repositório (AC: 4)**
   - **Given** um webhook `projects_v2_item` com `content_type == "DraftIssue"` ou qualquer evento onde o repositório não possa ser resolvido
   - **When** a resolução de repositório for executada
   - **Then** se não houver repositório padrão configurado (`DEFAULT_GITHUB_REPOSITORY`), a API deve rejeitar o evento com código HTTP 422 Unprocessable Entity e mensagem descritiva (`{"detail": "Repository could not be resolved for event"}`), sem salvar registros órfãos no banco de dados.

5. **Ajuste na Triagem de Webhooks: Aceitar `issues` com Ação `labeled` como `PENDING` (AC: 5)**
   - **Given** um webhook com `X-GitHub-Event: issues` e payload contendo `"action": "labeled"`
   - **When** a função de triagem `classify_event_status` for executada
   - **Then** o status inicial do evento deve ser classificado como `"PENDING"` (elegível para consumo e execução pelo worker)
   - **And** todos os fluxos de triagem existentes (detecção de coluna "Ready" para `projects_v2_item` e `project_card`) devem ser preservados sem regressão.

6. **Extração do Código da História a Partir da Descrição da Issue no Worker (AC: 6)**
   - **Given** um evento associado a uma issue (ex: `payload.issue`) consumido pelo worker `ai-dev-executor`
   - **When** `_process_event` for acionado
   - **Then** o worker deve inspecionar a descrição (`issue.body`) e buscar pelo padrão de chave da história (ex: `Story Key:\s*([\w\-\.]+)` ou `Story:\s*([\w\-\.]+)`, capturando casos como `Story Key: 5-2-time-to-goal-motivational-clock`)
   - **And** caso a descrição não contenha o padrão de Story Key, o identificador da história (`story_id`) deve assumir o fallback `issue-<id>` (utilizando `issue.id` ou `issue.number`, ex: `issue-42`).

7. **Ajuste no Padrão de Nome de Branch no Git (`feature/<codigo_historia>`) (AC: 7)**
   - **Given** o código da história extraído (`story_id`, ex: `5-2-time-to-goal-motivational-clock` ou `issue-42`)
   - **When** o worker criar a branch de trabalho no Git para a sessão de execução
   - **Then** o nome da branch gerada deve seguir rigorosamente o padrão `feature/<codigo_historia>` (ex: `feature/5-2-time-to-goal-motivational-clock` ou `feature/issue-42`), eliminando prefixos legados adicionais como `feature/story-...`
   - **And** se o payload contiver explicitamente `head_branch` ou `branch`, esse valor terá precedência.

8. **Atualização dos Modelos de Persistência e Repositório (`EventRecord` e `EventRepository`) (AC: 8)**
   - **Given** o módulo de persistência em `persistence/src/repository.py`
   - **When** operações de inserção, `claim_event`, e consulta forem executadas
   - **Then** o modelo `EventRecord` deve conter o campo `repository: Optional[str] = None`
   - **And** `claim_event` e queries de consulta devem incluir `events.repository` no retorno e aceitar filtro opcional por `repository: Optional[str] = None` ou lista de repositórios.

9. **Uso Prioritário de `event.repository` no `ai-dev-executor` (AC: 9)**
   - **Given** o worker `ai-dev-executor` processando um evento reivindicado
   - **When** `_process_event` for acionado
   - **Then** ele deve ler prioritariamente `event.repository` do `EventRecord`, utilizando como fallback secundário `payload.repository` e como fallback terciário `settings.GITHUB_REPOSITORY`.

10. **Suíte de Testes Automatizados Completa (AC: 10)**
    - **Given** as implementações nos pacotes `ai-dev-api`, `persistence` e `ai-dev-executor`
    - **When** a suíte de testes `pytest` for executada
    - **Then** os testes automatizados devem cobrir com 100% de sucesso:
      - Migração Alembic 005 (upgrade e downgrade) em `tests/persistence/test_migrations.py`
      - Inserção, `claim_event` e isolamento com coluna `repository` no `EventRepository` em `tests/persistence/test_event_consumption.py` e `test_repository.py`
      - Endpoint `POST /webhooks/github` com resolução nativa de repo, resolução GraphQL mockada, rejeição 422 para eventos sem repo, e triagem de `issues` com `action: "labeled"` como `PENDING` em `tests/api/test_webhooks.py`
      - Extração do código da história do body da issue, fallback `issue-<id>`, criação de branch `feature/<codigo_historia>` e leitura de `event.repository` em `tests/executor/test_worker.py`.

---

## Tasks / Subtasks

- [x] Task 1: Criar Migração Alembic `005_add_repository_column_to_events.py` e atualizar modelos de persistência (AC: 1, 8)
  - [x] Criar arquivo `persistence/src/migrations/versions/005_add_repository_column_to_events.py` com `revises = '004_add_error_log_to_events'`, adicionando a coluna `repository VARCHAR(255) NULL` e índices `idx_events_repository` e `idx_events_repository_status`
  - [x] Implementar `downgrade()` com remoção dos índices e da coluna `repository`
  - [x] Atualizar `EventRecord` em `persistence/src/repository.py` adicionando campo `repository: Optional[str] = None`
  - [x] Atualizar `EventRepository.claim_event` e queries de listagem/inserção para retornar e aceitar filtro opcional `repository: Optional[str] = None`

- [x] Task 2: Configuração e Serviço de Resolução de Repositório no `ai-dev-api` (AC: 2, 3, 4)
  - [x] Adicionar `DEFAULT_GITHUB_REPOSITORY: Optional[str] = None` em `api/src/config.py`
  - [x] Criar serviço / helper `api/src/services/github_resolver.py` com função assíncrona `resolve_repository_from_event(event_type: str, payload: dict, token: Optional[str] = None, api_url: Optional[str] = None, http_client: Optional[httpx.AsyncClient] = None) -> Optional[str]`
  - [x] Implementar extração de payload nativo (`payload.repository.full_name`, `payload.repository.name_with_owner`, ou string `payload.repository`)
  - [x] Implementar consulta GraphQL `node(id: $nodeId)` para obter `nameWithOwner` quando `projects_v2_item` possuir `content_node_id` ou `node_id`

- [x] Task 3: Ajuste na Triagem de Webhooks para `issues` com `action: labeled` (AC: 5)
  - [x] Atualizar `classify_event_status` em `api/src/services/triage.py` para retornar `"PENDING"` quando `event_type == "issues"` e `payload.get("action") == "labeled"`
  - [x] Manter intactas as regras existentes para detecção de colunas "Ready" de `projects_v2_item` e `project_card`

- [x] Task 4: Atualização da Rota `POST /webhooks/github` (`api/src/routes/webhooks.py`) (AC: 2, 3, 4)
  - [x] Integrar `resolve_repository_from_event` no fluxo do endpoint antes da gravação no banco
  - [x] Se o repositório não for resolvido e não houver `DEFAULT_GITHUB_REPOSITORY`, lançar `HTTPException(status_code=422, detail="Repository could not be resolved for event")`
  - [x] Incluir `repository` na query SQL `INSERT INTO events (event_id, event_type, status, payload, repository, retry_count)` e no retorno JSON da resposta HTTP 202 Accepted

- [x] Task 5: Extração de Código da História da Issue e Ajuste do Padrão de Branch no Worker (`executor/src/worker.py`) (AC: 6, 7, 9)
  - [x] Atualizar `_process_event` para utilizar `event.repository` como primeira prioridade para o nome do repositório
  - [x] Implementar função/lógica de extração de código da história:
    - Inspecionar `issue.get("body", "")` buscando por regex `r"Story Key:\s*([a-zA-Z0-9_\-\.]+)"` ou `r"Story:\s*([a-zA-Z0-9_\-\.]+)"`
    - Se encontrado, definir `story_id = match.group(1).strip()`
    - Se não encontrado, adotar fallback `story_id = f"issue-{issue_data.get('id') or issue_data.get('number', event.event_id)}"`
  - [x] Ajustar a geração do nome da branch padrão para `feature/<codigo_historia>`:
    - Formatar `head_branch = payload.get("head_branch") or payload.get("branch") or f"feature/{story_id}"`

- [x] Task 6: Suíte de Testes Automatizados (AC: 10)
  - [x] Atualizar `tests/persistence/test_migrations.py` validando o upgrade e downgrade da migração 005
  - [x] Atualizar `tests/persistence/test_event_consumption.py` e `test_repository.py` com o campo `repository`
  - [x] Adicionar testes em `tests/api/test_webhooks.py`:
    - Resolução direta de repositório em webhook nativo
    - Resolução de repositório via GraphQL mockado para `projects_v2_item`
    - Rejeição HTTP 422 para eventos sem repositório (DraftIssues)
    - Triagem de webhook `issues` com `action: "labeled"` retornando status `PENDING`
  - [x] Adicionar testes em `tests/executor/test_worker.py`:
    - Extração de `Story Key: 5-2-time-to-goal-motivational-clock` da descrição da issue
    - Fallback para `issue-<id>` quando a descrição não possuir Story Key
    - Formação de branch name `feature/<codigo_historia>`
    - Prioridade de leitura de `event.repository`
  - [x] Executar `.venv/bin/pytest` garantindo 100% de aprovação

### Review Findings

- [x] [Review][Patch] Prioridade de number sobre id no fallback de identificador de issue [executor/src/worker.py:34]
- [x] [Review][Patch] Tratamento defensivo de data: null em respostas GraphQL em github_resolver.py [api/src/services/github_resolver.py:70]
- [x] [Review][Patch] Tratamento defensivo de data: null em respostas GraphQL em triage.py [api/src/services/triage.py:76]
- [x] [Review][Patch] Suporte a ProjectV2Item com navegação para content na consulta GraphQL de repositório [api/src/services/github_resolver.py:28]
- [x] [Review][Patch] Remoção de pontuação final em Story Key extraída do body da issue [executor/src/worker.py:33]

---

## Dev Notes

### Contexto de Arquitetura & Guardrails

- **AD-1 (Persistência de Webhook no Event Store):** Todo webhook recebido deve ser validado quanto à assinatura, triado quanto à elegibilidade (`PENDING` vs `IGNORED`), e enriquecido com a coluna `repository` antes de ser persistido atomicamente no PostgreSQL.
- **AD-2 (Consumo via PostgreSQL com SKIP LOCKED):** O worker `ai-dev-executor` consulta a tabela `events` usando `claim_event`. Com a nova coluna `repository`, workers podem filtrar ou rotear execuções para instâncias específicas por repositório.
- **AD-4 (Propriedade do GitHub):** O worker utiliza o `repository` resolvido para executar o clone via `git_manager` e abrir Pull Requests via `github_client`.
- **Zero Deferred Work:** Todos os achados de revisão e tarefas desta história devem ser concluídos na própria história sem pendências.

### Files Being Modified / Created

| File | Operation | Description |
|---|---|---|
| `persistence/src/migrations/versions/005_add_repository_column_to_events.py` | NEW | Migração Alembic adicionando coluna `repository` e índices `idx_events_repository`, `idx_events_repository_status` |
| `persistence/src/repository.py` | UPDATE | Suporte ao campo `repository` no `EventRecord` e nas queries do `EventRepository` |
| `api/src/config.py` | UPDATE | Configuração `DEFAULT_GITHUB_REPOSITORY` |
| `api/src/services/github_resolver.py` | NEW | Serviço de resolução de repositório via payload e GraphQL API v4 |
| `api/src/services/triage.py` | UPDATE | Triagem de eventos `issues` com `action: "labeled"` como `PENDING` |
| `api/src/routes/webhooks.py` | UPDATE | Resolução obrigatória de `repository`, rejeição 422 e persistência com nova coluna |
| `executor/src/worker.py` | UPDATE | Uso prioritário de `event.repository`, extração de Story Key do body da issue, fallback `issue-<id>` e branch `feature/<codigo_historia>` |
| `tests/persistence/test_migrations.py` | UPDATE | Testes de migração da versão 005 (upgrade e downgrade) |
| `tests/persistence/test_event_consumption.py` | UPDATE | Testes do `EventRepository` com coluna `repository` |
| `tests/api/test_webhooks.py` | UPDATE | Testes de resolução de repositório, rejeição 422 e triagem de issue labeled |
| `tests/executor/test_worker.py` | UPDATE | Testes de extração de Story Key, fallback de issue, branch `feature/<codigo_historia>` e `event.repository` |

### Detalhes Técnicos de Implementação

#### 1. Consulta GraphQL para Resolução de Repositório (`projects_v2_item`)
```graphql
query GetRepoFromContentNode($nodeId: ID!) {
  node(id: $nodeId) {
    ... on Issue {
      number
      title
      repository {
        nameWithOwner
      }
    }
    ... on PullRequest {
      number
      title
      repository {
        nameWithOwner
      }
    }
  }
}
```

#### 2. Lógica de Extração de Código de História da Issue no Worker
```python
import re

def extract_story_id_from_issue(issue_data: dict, fallback_id: str) -> str:
    body = issue_data.get("body") or ""
    # Padrões comuns: "Story Key: 5-2-time-to-goal-motivational-clock" ou "Story: 5-2-..."
    match = re.search(r"(?:Story\s*Key|Story):\s*([a-zA-Z0-9_\-\.]+)", body, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    # Fallback caso não seja possível extrair da descrição: issue-<id> ou issue-<number>
    issue_num = issue_data.get("number") or issue_data.get("id") or fallback_id
    return f"issue-{issue_num}"
```

#### 3. Padrão de Branch no Worker
```python
# Padrão: feature/<codigo_historia>
# Exemplo: feature/5-2-time-to-goal-motivational-clock ou feature/issue-42
head_branch = payload.get("head_branch") or payload.get("branch") or f"feature/{story_id}"
```

### Project Structure Notes

- `api/src/services/github_resolver.py` mantém a separação de responsabilidades entre triagem de status (`triage.py`) e resolução de entidades remotas do GitHub (`github_resolver.py`).
- As migrações do Alembic em `persistence/src/migrations/versions/` seguem a sequência estrita `001_initial_schema` -> `002_add_events_consumption_index` -> `003_add_agent_memory_event_id_and_unique_constraint` -> `004_add_error_log_to_events` -> `005_add_repository_to_events`.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story-1.4](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/epics.md)
- [Source: _bmad-output/planning-artifacts/architecture/architecture-AI%20Developer-2026-08-09/ARCHITECTURE-SPINE.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/architecture/architecture-AI%20Developer-2026-08-09/ARCHITECTURE-SPINE.md)
- [Source: api/src/services/triage.py](file:///Users/alexandrofs/projects/aidev/api/src/services/triage.py)
- [Source: executor/src/worker.py](file:///Users/alexandrofs/projects/aidev/executor/src/worker.py)
- [Source: persistence/src/repository.py](file:///Users/alexandrofs/projects/aidev/persistence/src/repository.py)

---

## Dev Agent Record

### Agent Model Used

Gemini 3.7 Flash (High)

### Debug Log References

- Identificado e resolvido limite de tamanho da coluna `version_num` da tabela `alembic_version` (VARCHAR(32)) ajustando o identifier da revisão 005 para `005_add_repository_to_events`.

### Completion Notes List

- Migração Alembic `005_add_repository_to_events` criada e testada com sucesso (upgrade e downgrade) adicionando a coluna `repository VARCHAR(255) NULL` e os índices `idx_events_repository` e `idx_events_repository_status`.
- Modelos `EventRecord` e `EventRepository` atualizados com suporte a `repository` e filtragem por repositório em `claim_event`.
- Criado `api/src/services/github_resolver.py` com resolução de repositório nativo e via GraphQL para `projects_v2_item`.
- Adicionado `DEFAULT_GITHUB_REPOSITORY` em `api/src/config.py` e validação HTTP 422 para webhooks sem repositório resolúvel.
- Triagem em `api/src/services/triage.py` atualizada para classificar webhooks `issues` com `action: "labeled"` como `PENDING`.
- Worker `executor/src/worker.py` atualizado com prioridade de leitura de `event.repository`, extração de `Story Key` da issue com fallback `issue-<id>`, e formato de branch `feature/<codigo_historia>`.
- Suíte completa de 135 testes automatizados aprovada com 100% de sucesso.

### File List

- `persistence/src/migrations/versions/005_add_repository_column_to_events.py`
- `persistence/src/repository.py`
- `api/src/config.py`
- `api/src/services/github_resolver.py`
- `api/src/services/triage.py`
- `api/src/routes/webhooks.py`
- `executor/src/worker.py`
- `tests/api/conftest.py`
- `tests/api/test_webhooks.py`
- `tests/executor/test_worker.py`
- `tests/persistence/test_event_consumption.py`
- `tests/persistence/test_migrations.py`
- `_bmad-output/implementation-artifacts/1-4-adicao-da-coluna-repository-no-event-store-e-resolucao-de-webhooks.md`

