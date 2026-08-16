---
baseline_commit: 1a234736c250a98f33ccc0eabe036767a578c491
---

# Story 1.4: Adição da Coluna Repository no Event Store e Resolução de Repositório em Webhooks

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a sistema AIDEV,
I want que a tabela de eventos do PostgreSQL possua uma coluna dedicada `repository` e que o endpoint de webhooks resolva o repositório alvo (inclusive consultando o GitHub GraphQL para eventos de Projects v2) antes de persistir o evento,
so that todos os eventos no Event Store possuam um repositório alvo válido e garantido, viabilizando consumo multi-repo e eliminando falhas tardias no worker.

## Acceptance Criteria

1. **Migração de Banco de Dados: Adição da Coluna `repository` no Event Store (AC: 1)**
   - **Given** a base de dados PostgreSQL existente com a tabela `events`
   - **When** a migration `004_add_repository_column_to_events.py` do Alembic for aplicada
   - **Then** a coluna `repository VARCHAR(255) NULL` deve ser adicionada à tabela `events`
   - **And** os índices `idx_events_repository` em `('repository')` e `idx_events_repository_status` em `('repository', 'status')` devem ser criados
   - **And** o downgrade da migração deve remover os índices e a coluna de forma idempotente e reversível.

2. **Resolução de Repositório para Webhooks Nativos de Repositório (AC: 2)**
   - **Given** um webhook com payload JSON contendo o objeto de repositório (ex: `payload.repository.full_name` ou `repository.nameWithOwner`)
   - **When** o endpoint `POST /webhooks/github` processar a requisição
   - **Then** o valor de `repository` deve ser extraído diretamente do payload (formato `owner/repo`) e persistido na coluna `repository` da tabela `events`
   - **And** a resposta HTTP 202 Accepted deve incluir o campo `repository`.

3. **Resolução Dinâmica de Repositório para Itens de GitHub Projects v2 (`projects_v2_item`) via GraphQL API (AC: 3)**
   - **Given** um webhook `projects_v2_item` onde `projects_v2_item.content_type` seja `"Issue"` ou `"PullRequest"` e contenha `content_node_id`
   - **When** o webhook for recebido em `POST /webhooks/github`
   - **Then** a API deve realizar uma consulta GraphQL (`node(id: $content_node_id) { ... on Issue { repository { nameWithOwner } } ... on PullRequest { repository { nameWithOwner } } }`) usando o `GITHUB_TOKEN`
   - **And** extrair o repositório (`nameWithOwner`, ex: `owner/repo`) e persistir o registro com `repository = nameWithOwner`.

4. **Validação e Rejeição de Eventos sem Resolução de Repositório (AC: 4)**
   - **Given** um webhook `projects_v2_item` com `content_type == "DraftIssue"` ou qualquer evento onde o repositório não possa ser resolvido
   - **When** a resolução de repositório for executada
   - **Then** se não houver repositório padrão configurado (`DEFAULT_GITHUB_REPOSITORY`), a API deve rejeitar o evento com código HTTP 422 Unprocessable Entity e mensagem descritiva ("Repository could not be resolved for event"), sem salvar registros órfãos no banco de dados.

5. **Atualização dos Repositórios de Persistência e Entidades (`EventRecord` e `EventRepository`) (AC: 5)**
   - **Given** o módulo de persistência em `persistence/src/repository.py`
   - **When** operações de `claim_event`, `list_events`, e inserção forem executadas
   - **Then** o modelo `EventRecord` deve conter o campo `repository: Optional[str] = None`
   - **And** `claim_event` e `list_events` devem suportar filtro opcional por `repository: Optional[str] = None`.

6. **Atualização do Worker para Consumo com Repositório Validado (AC: 6)**
   - **Given** o worker `ai-dev-executor` processando um evento reivindicado
   - **When** `_process_event` for acionado
   - **Then** ele deve ler prioritariamente `event.repository` do `EventRecord`, repassando-o para clonagem, branch setup, commits e criação do Pull Request.

7. **Suíte de Testes Automatizados (AC: 7)**
   - **Given** as implementações no `ai-dev-api`, `persistence` e `ai-dev-migrations`
   - **When** `pytest` for executado
   - **Then** os testes devem cobrir:
     - Upgrade e downgrade da migração Alembic 004
     - Endpoint `/webhooks/github` com webhooks de repositório (extração direta de `repository`)
     - Endpoint `/webhooks/github` com `projects_v2_item` (resolução via GraphQL mockado)
     - Endpoint `/webhooks/github` com `DraftIssue` (rejeição com HTTP 422)
     - Inserção e claim de eventos com coluna `repository` no `EventRepository`.

---

## Tasks / Subtasks

- [ ] Task 1: Criar Migration Alembic `004_add_repository_column_to_events.py` e atualizar modelos de persistência (AC: 1, 5)
  - [ ] Criar arquivo `persistence/src/migrations/versions/004_add_repository_column_to_events.py` adicionando a coluna `repository` e índices `idx_events_repository` e `idx_events_repository_status`
  - [ ] Atualizar `EventRecord` em `persistence/src/repository.py` adicionando campo `repository: Optional[str] = None`
  - [ ] Atualizar `EventRepository.claim_event` e queries de listagem para aceitar filtro opcional `repository: Optional[str] = None`

- [ ] Task 2: Configuração e Cliente GraphQL para Resolução de Repositório no `ai-dev-api` (AC: 3, 4)
  - [ ] Adicionar `GITHUB_TOKEN`, `GITHUB_API_URL` e `DEFAULT_GITHUB_REPOSITORY` em `api/src/config.py`
  - [ ] Criar serviço / helper `api/src/services/github_resolver.py` com função assíncrona `resolve_repository_from_event(event_type: str, payload: dict) -> Optional[str]`
  - [ ] Implementar chamada GraphQL para consultar `node(id: $content_node_id)` quando `event_type == 'projects_v2_item'`

- [ ] Task 3: Atualização da Rota `POST /webhooks/github` (`api/src/routes/webhooks.py`) (AC: 2, 3, 4)
  - [ ] Integrar `resolve_repository_from_event` no fluxo da rota antes do `INSERT`
  - [ ] Se o repositório não for resolvido, retornar `HTTPException(status_code=422, detail="Repository could not be resolved for event")`
  - [ ] Incluir `repository` no `INSERT INTO events` e na resposta JSON do endpoint

- [ ] Task 4: Atualização do `ai-dev-executor` (`executor/src/worker.py`) (AC: 6)
  - [ ] Atualizar `_process_event` para utilizar `event.repository` como fonte primária do nome do repositório
  - [ ] Garantir compatibilidade retroativa caso `event.repository` seja `None`

- [ ] Task 5: Suíte de Testes Automatizados (AC: 7)
  - [ ] Atualizar `tests/persistence/test_migrations.py` para validar migration 004
  - [ ] Atualizar `tests/persistence/test_event_consumption.py` e `test_repository.py` com a coluna `repository`
  - [ ] Adicionar testes em `tests/api/test_webhooks.py` cobrindo resolução direta, resolução via GraphQL mockado e rejeição HTTP 422 para DraftIssues sem repo
  - [ ] Executar `.venv/bin/pytest` garantindo 100% de aprovação

---

## Dev Notes

### Files Being Modified / Created

| File | Operation | Description |
|---|---|---|
| `persistence/src/migrations/versions/004_add_repository_column_to_events.py` | NEW | Migration Alembic adicionando coluna `repository` e índices |
| `persistence/src/repository.py` | UPDATE | Suporte ao campo `repository` no `EventRecord` e `EventRepository` |
| `api/src/config.py` | UPDATE | Adicionar configurações do GitHub (`GITHUB_TOKEN`, `DEFAULT_GITHUB_REPOSITORY`, etc.) |
| `api/src/services/github_resolver.py` | NEW | Serviço de resolução de repositório via payload e GraphQL |
| `api/src/routes/webhooks.py` | UPDATE | Validação obrigatória de repositório antes do INSERT |
| `executor/src/worker.py` | UPDATE | Uso prioritário de `event.repository` no processamento de eventos |
| `docker-compose.yml` | UPDATE | Injetar `GITHUB_TOKEN` e `DEFAULT_GITHUB_REPOSITORY` no serviço `ai-dev-api` |
| `tests/api/test_webhooks.py` | UPDATE | Testes unitários para resolução e rejeição 422 |
| `tests/persistence/test_migrations.py` | UPDATE | Testes de migração da versão 004 |

### GraphQL Query Example for Projects v2 Items
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
