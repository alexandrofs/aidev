---
title: 'Ajustes no fluxo de triagem de eventos de webhook: coluna error_log, status IGNORED e elegibilidade via coluna Ready'
type: 'feature'
created: '2026-08-16T18:19:00-03:00'
baseline_commit: '11eca3042e9f7dfc52f95607003b45c59982ba37'
status: 'done'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** O sistema atualmente ingere todos os webhooks como `PENDING` sem filtrar se o item está pronto para execução no GitHub Projects, não possui o status `IGNORED` para descartar eventos inelegíveis no Event Store, e não possui uma coluna dedicada `error_log` na tabela `events` para armazenar detalhes e logs de erros ocorridos durante falhas de execução. Além disso, eventos do tipo `projects_v2_item` (como `reordered` ou `edited`) frequentemente não incluem o campo de status inline no payload, necessitando de resolução dinâmica para confirmar se o item está na coluna "Ready".

**Approach:** Adicionar a coluna `error_log` na tabela `events` via migração Alembic e atualizar o `EventRepository` e `EventRecord` para gravar mensagens de erro em falhas. Implementar a lógica de triagem no `ai-dev-api` que avalia a elegibilidade de webhooks (verificando se o evento pertence à coluna "Ready" de um projeto via payload direto ou consulta GraphQL pelo `node_id` de `projects_v2_item`), persistindo com status `PENDING` se elegível ou `IGNORED` se não estiver em "Ready".

## Boundaries & Constraints

**Always:**
- Garantir que a migração Alembic seja reversível (upgrade e downgrade funcionais).
- Gravar o log/detalhes de erro na coluna `error_log` da tabela `events` sempre que `fail_event` for chamado no `EventRepository`.
- Permitir que eventos em status `IGNORED` fiquem registrados no Event Store para auditoria e rastreabilidade, mas nunca sejam reivindicados pelo `claim_event` do worker.
- Avaliar case-insensitively o nome da coluna/status do projeto para `"Ready"` (ex: `"Ready"`, `"ready"`, `"READY"`).
- Para eventos `projects_v2_item` onde o status não venha explícito em `changes.field_value` (ex: `action: "reordered"` com `previous_projects_v2_item_node_id`), consultar a API GraphQL do GitHub (`node(id: $node_id) { ... on ProjectV2Item { fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } } } }`) quando `GITHUB_TOKEN` estiver disponível. Se o status não for "Ready" ou a consulta falhar/não houver token, classificar como `IGNORED`.

**Ask First:**
- Nenhuma alteração estrutural não solicitada em outras tabelas (`agent_memory`, `audit_logs`).

**Never:**
- Não quebrar a retrocompatibilidade das APIs e endpoints existentes (`/healthz`, `/webhooks/github`).
- Não permitir que workers processem eventos que não estejam no status `PENDING`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Webhook Projects v2 em "Ready" (inline em changes) | Evento `projects_v2_item` com `changes.field_value.to.name == "Ready"` | Persistido com `status = 'PENDING'`, retornado HTTP 202 Accepted | Salva no banco com status `PENDING` |
| Webhook Projects v2 reordered com GraphQL status "Ready" | Evento `projects_v2_item` (`action: "reordered"`, `node_id: "PVTI_..."`), GraphQL retorna status "Ready" | Persistido com `status = 'PENDING'`, retornado HTTP 202 Accepted | Salva no banco com status `PENDING` |
| Webhook Projects v2 fora de "Ready" (ex: "Todo", "Backlog", "In Progress") | Evento `projects_v2_item` com coluna "Todo" ou GraphQL retornando "Todo" | Persistido com `status = 'IGNORED'`, retornado HTTP 202 com `status: "IGNORED"` | Salva no banco com status `IGNORED` |
| Webhook Classic Project card em "Ready" | Evento `project_card` com `column_name = "Ready"` | Persistido com `status = 'PENDING'` | Salva no banco com status `PENDING` |
| Webhook Classic Project card fora de "Ready" | Evento `project_card` com `column_name = "In Review"` | Persistido com `status = 'IGNORED'` | Salva no banco com status `IGNORED` |
| Webhook Issue / outro evento sem indicação de Ready | Evento `issues` ou `workflow_run` sem flag/coluna "Ready" | Persistido com `status = 'IGNORED'` | Salva no banco com status `IGNORED` |
| Falha de execução do worker | `fail_event(event_id, worker_id, error_message)` é chamado | Atualiza `events.error_log = error_message` e ajusta `status` (`PENDING` retry ou `FAILED`) | Gravado no banco e audit_logs |

</frozen-after-approval>

## Code Map

- `persistence/src/migrations/versions/004_add_error_log_to_events.py` -- Migração Alembic adicionando coluna `error_log TEXT NULL` à tabela `events`.
- `persistence/src/repository.py` -- Atualização do modelo `EventRecord`, do método `fail_event` para persistir `error_log`, e suporte ao status `IGNORED`.
- `api/src/config.py` -- Inclusão de `GITHUB_TOKEN` e `GITHUB_API_URL` nas configurações da API para suporte à resolução GraphQL.
- `api/src/services/triage.py` -- Serviço de triagem de eventos de webhook para verificar se o evento está na coluna "Ready" (inspeção inline e resolução GraphQL de `ProjectV2Item`).
- `api/src/routes/webhooks.py` -- Ingestão e persistência do evento utilizando a triagem para definir status `PENDING` vs `IGNORED`.
- `tests/persistence/test_migrations.py` -- Validação da migração Alembic 004 (upgrade e downgrade).
- `tests/persistence/test_event_consumption.py` -- Testes unitários do `EventRepository` validando a gravação de `error_log` e exclusão de `IGNORED` no `claim_event`.
- `tests/api/test_webhooks.py` -- Testes de API para triagem de eventos em coluna Ready (`PENDING`), eventos `reordered` com GraphQL mockado, e eventos fora de Ready (`IGNORED`).

## Tasks & Acceptance

**Execution:**
- [x] `persistence/src/migrations/versions/004_add_error_log_to_events.py` -- Criar migração Alembic -- Adicionar coluna `error_log` na tabela `events`.
- [x] `persistence/src/repository.py` -- Atualizar `EventRecord` e `fail_event` -- Gravar mensagens de erro na coluna `error_log` e suportar status `IGNORED`.
- [x] `api/src/config.py` -- Atualizar configurações da API -- Adicionar `GITHUB_TOKEN` e `GITHUB_API_URL`.
- [x] `api/src/services/triage.py` -- Criar serviço de triagem assíncrono `classify_event_status(event_type: str, payload: dict, token: Optional[str] = None, api_url: Optional[str] = None) -> str` -- Suportar checagem inline e fallback GraphQL para `projects_v2_item`.
- [x] `api/src/routes/webhooks.py` -- Integrar triagem no endpoint `POST /webhooks/github` -- Definir status inicial como `PENDING` (se Ready) ou `IGNORED` (se não Ready).
- [x] `tests/persistence/test_migrations.py` -- Adicionar testes para migração 004 -- Garantir upgrade e downgrade corretos.
- [x] `tests/persistence/test_event_consumption.py` -- Adicionar testes para `error_log` em `fail_event` e garantir que eventos `IGNORED` não são consumidos por `claim_event`.
- [x] `tests/api/test_webhooks.py` -- Atualizar e adicionar testes de triagem no endpoint `/webhooks/github` cobrindo eventos Ready (`PENDING`), eventos `reordered` via GraphQL mockado, e eventos não-Ready (`IGNORED`).

**Acceptance Criteria:**
- Given a tabela `events` existente, when a migração 004 for aplicada, then a coluna `error_log` deve existir e aceitar texto longo ou nulo.
- Given um evento em processamento que falha, when `fail_event` for executado com uma mensagem de erro, then a coluna `error_log` do registro deve conter exatamente a mensagem de erro fornecida.
- Given um webhook `projects_v2_item` com ação `reordered` ou `edited`, when o status no projeto for `"Ready"`, then o registro no banco deve ser criado com `status = 'PENDING'`.
- Given um webhook `projects_v2_item` com status diferente de `"Ready"`, when recebido em `POST /webhooks/github`, then o registro no banco deve ser criado com `status = 'IGNORED'`.
- Given eventos na tabela `events` com status `IGNORED`, when `claim_event` for invocado por workers, then nenhum evento `IGNORED` deve ser retornado ou travado.

## Spec Change Log

- **2026-08-16**: Adicionado suporte específico para payloads `projects_v2_item` com ação `reordered` sem campos inline de status, utilizando consulta GraphQL `node(id: $node_id)` para inspecionar o valor do campo "Status".

## Verification

**Commands:**
- `.venv/bin/pytest tests/persistence/test_migrations.py` -- expected: Migração 004 executada com sucesso em upgrade e downgrade.
- `.venv/bin/pytest tests/persistence/test_event_consumption.py` -- expected: `error_log` e status `IGNORED` validados no repositório de eventos.
- `.venv/bin/pytest tests/api/test_webhooks.py` -- expected: Endpoint `/webhooks/github` validado para status `PENDING` e `IGNORED` (incluindo `reordered`).
- `.venv/bin/pytest` -- expected: Suíte completa de testes passando com 100% de sucesso.

## Suggested Review Order

**Triagem de Webhooks e Elegibilidade por Coluna Ready**

- Serviço central que classifica eventos como PENDING ou IGNORED baseado em coluna Ready.
  [`triage.py:65`](../../api/src/services/triage.py#L65)

- Ingestão na rota HTTP com persistência do status triado.
  [`webhooks.py:34`](../../api/src/routes/webhooks.py#L34)

- Configurações de API com token e URL do GitHub.
  [`config.py:6`](../../api/src/config.py#L6)

**Persistência de Logs de Falha e Status IGNORED**

- Registro de mensagens de erro na nova coluna error_log em fail_event.
  [`repository.py:200`](../../persistence/src/repository.py#L200)

- Migração Alembic 004 adicionando coluna error_log na tabela events.
  [`004_add_error_log_to_events.py:20`](../../persistence/src/migrations/versions/004_add_error_log_to_events.py#L20)

**Suíte de Testes Automatizados**

- Testes de ponta a ponta da rota de webhook para eventos Ready e IGNORED.
  [`test_webhooks.py:173`](../../tests/api/test_webhooks.py#L173)

- Testes unitários do EventRepository para gravação de error_log e isolamento de IGNORED.
  [`test_event_consumption.py:170`](../../tests/persistence/test_event_consumption.py#L170)

- Testes de migração Alembic para upgrade e downgrade da versão 004.
  [`test_migrations.py:102`](../../tests/persistence/test_migrations.py#L102)

