---
baseline_commit: 36ff1af92492d2263f56e85fde47cf0e91ab7af5
---

# Story 3.2: Geração e Abertura Semântica de Pull Requests para Revisão Humana

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a revisor humano,
I want receber um Pull Request estruturado no GitHub com a descrição clara das alterações, contexto da história e evidências das validações locais (via `gh` CLI / GitHub API Client),
so that eu possa realizar a revisão de código final com agilidade, segurança e total rastreabilidade.

## Acceptance Criteria

1. **Geração Semântica de Metadados do Pull Request (AC: 1)**
   - **Given** a aprovação das fases de desenvolvimento (`coding`), revisão interna (`review`) e validação local (`ValidationPipeline`) no sandbox
   - **When** o `ai-dev-executor` iniciar a preparação para entrega do código
   - **Then** o sistema deve gerar um título semântico padronizado seguindo a convenção Conventional Commits (ex: `feat(story-3.2): <descrição concisa>`)
   - **And** deve compilar o corpo (*body*) do PR em Markdown estruturado contendo:
     - Resumo executivo das alterações implementadas
     - Referência rastreável à história e link/ID do card no GitHub Projects v2
     - Evidências das validações locais executadas (testes unitários, linters, exit codes)
     - Resumo do Code Review interno e conformidade com a política *Zero Deferred Work*.

2. **Publicação de Branch e Abertura do Pull Request no GitHub (AC: 2)**
   - **Given** o repositório local no workspace isolado com as alterações commitadas
   - **When** a etapa de publicação for acionada pelo `GitHubClient` / executor
   - **Then** o branch de trabalho dedicado (ex: `aidev/story-<id>` ou `feature/story-<id>`) deve ser publicado no repositório remoto via autenticação segura com token (`GITHUB_TOKEN`)
   - **And** uma Pull Request deve ser criada contra o branch base configurado (ex: `main`), retornando os metadados do PR (`pr_number`, `pr_url`, `pr_html_url`, `head_branch`, `base_branch`, `commit_sha`).

3. **Sincronização de Status com o GitHub Projects v2 (AC: 3)**
   - **Given** o Pull Request aberto com sucesso no GitHub
   - **When** o identificador do item/card de projeto estiver presente no payload do evento (`project_item_id` / `project_id`)
   - **Then** o `GitHubClient` deve realizar mutação GraphQL (`updateProjectV2ItemFieldValue`) para transicionar o card para a coluna de revisão humana (ex: `"In Review"` ou `"Review"`)
   - **And** vincular a URL da Pull Request aos comentários ou campos de rastreio do card.

4. **Persistência de Metadados, Conclusão do Evento e Audit Logs no PostgreSQL (AC: 4)**
   - **Given** a conclusão bem-sucedida da criação do PR e sincronização do GitHub Projects
   - **When** o `ExecutorWorker` finalizar o ciclo do evento
   - **Then** os logs de auditoria estruturados `PR_CREATION_STARTED`, `PR_CREATED` e `PROJECTS_CARD_UPDATED` devem ser gravados na tabela `audit_logs`
   - **And** o evento deve ser marcado como `COMPLETED` no `EventRepository`, com os detalhes persistidos contendo `pr_url`, `pr_number`, `branch`, `commit_sha` e resumo de validação
   - **And** a memória hierárquica (Nível 2 em `agent_memory` e Nível 3 em `.memlog.md`) deve ser atualizada com o link do PR e status final.

5. **Tratamento de Falhas e Isolamento de Erros de Integração Externa (AC: 5)**
   - **Given** uma falha de rede, erro de autenticação (401/403) ou conflito na API do GitHub
   - **When** a tentativa de push, criação de PR ou atualização do Projects v2 falhar
   - **Then** o sistema deve emitir o log de auditoria `PR_FAILED` com os detalhes estruturados do erro
   - **And** o evento deve ser tratado pelo mecanismo de retentativas (`fail_event`), incrementando `retry_count` e retornando a `PENDING` ou marcando `FAILED` sem corromper o estado do banco.

6. **Suíte de Testes Automatizados (Unitários e de Integração com Mocks) (AC: 6)**
   - **Given** o novo cliente de integração `GitHubClient` e as extensões no `ExecutorWorker`
   - **When** a suíte de testes for executada com `pytest`
   - **Then** testes unitários e de integração em `tests/executor/` devem cobrir:
     - Geração do corpo semântico e título do PR a partir dos resultados de validação e memória
     - Fluxo de push de branch e criação de PR mockando chamadas HTTP/GraphQL do GitHub
     - Sincronização do card no GitHub Projects v2
     - Tratamento gracioso de falhas na API do GitHub e acionamento de retry
     - 100% de aprovação na suíte completa de testes do projeto sem regressões.

---

## Tasks / Subtasks

- [x] Task 1: Definição de Configurações do GitHub em `ExecutorSettings` (`executor/src/config.py`) (AC: 2, 3)
  - [x] Adicionar campos de configuração: `GITHUB_TOKEN: Optional[str]`, `GITHUB_REPOSITORY: Optional[str]`, `GITHUB_API_URL: str = "https://api.github.com"`, `GITHUB_BASE_BRANCH: str = "main"`, `GITHUB_PROJECT_ID: Optional[str]`
  - [x] Adicionar flags de modo de execução e simulação/dry-run para testes locais (`GITHUB_DRY_RUN: bool = False`)

- [x] Task 2: Implementação do Módulo de Integração `GitHubClient` (`executor/src/github.py`) (AC: 1, 2, 3, 5)
  - [x] Implementar classe `GitHubClient` com cliente assíncrono HTTP (`httpx.AsyncClient`)
  - [x] Implementar método `create_pull_request(repo, title, body, head_branch, base_branch)` via GitHub REST API v3 (`POST /repos/{owner}/{repo}/pulls`)
  - [x] Implementar método `format_semantic_pr_body(story_id, title, phase_results, validation_results, review_summary, project_item_id)` para compor corpo padronizado em Markdown
  - [x] Implementar método `update_project_card_status(project_id, item_id, field_id, option_id)` via GitHub GraphQL API v4
  - [x] Implementar tratamento robusto de erros (`GitHubAPIError`, `GitHubAuthError`) e logs contextuais

- [x] Task 3: Integração da Publicação de PR no `ExecutorWorker` (`executor/src/worker.py`) (AC: 1, 2, 3, 4, 5)
  - [x] Instanciar `GitHubClient` no `ExecutorWorker` (com suporte a injeção de dependência/mock)
  - [x] Ao término bem-sucedido da validação local (`validation_passed == True`), acionar fluxo de publicação:
    - Emitir audit log `PR_CREATION_STARTED`
    - Formatar título e corpo semântico do PR
    - Criar PR no GitHub remoto
    - Emitir audit log `PR_CREATED`
    - Sincronizar card no GitHub Projects v2 (se `project_item_id` presente) e emitir `PROJECTS_CARD_UPDATED`
  - [x] Persistir os dados do PR (`pr_number`, `pr_url`, `head_branch`, etc.) nos detalhes de `complete_event`
  - [x] Tratar exceções de publicação com audit log `PR_FAILED` e encaminhamento para `fail_event`

- [x] Task 4: Atualização da Memória Hierárquica com Links do PR (`executor/src/memory.py`) (AC: 4)
  - [x] Estender `summary_data` em `AgentMemoryManager` para incluir campos `pr_url`, `pr_number` e `pull_request_status`
  - [x] Garantir que o append no `.memlog.md` (Nível 3) inclua seção dedicada ao Pull Request gerado com link direto e instrução de revisão humana

- [x] Task 5: Suíte de Testes Automatizados (`tests/executor/test_github.py` e `tests/executor/test_worker.py`) (AC: 6)
  - [x] Criar `tests/executor/test_github.py` cobrindo formatação de PR, requisições REST/GraphQL mockadas, retries e erros de autenticação
  - [x] Atualizar `tests/executor/test_worker.py` para validar o fluxo ponta a ponta com abertura de PR e gravação de metadados
  - [x] Executar `.venv/bin/pytest` garantindo 100% de sucesso em todos os testes

### Review Findings

- [x] [Review][Patch] Corrigir potencial vazamento de conexões httpx quando _http_client é fornecido mas fechado [`executor/src/github.py:59-63`]
- [x] [Review][Patch] Validar existência de repositório de destino em modo não-dry-run para evitar requisições 404 para "local/repo" [`executor/src/worker.py:279-284`]
- [x] [Review][Patch] Sanitizar prefixos repetidos de 'story-' e '.git' em story_id, branch names e repo urls [`executor/src/github.py:69-76`, `executor/src/worker.py:284`]
- [x] [Review][Patch] Suporte defensivo a dicionários brutos e modelos Pydantic em format_semantic_pr_body e complete_event [`executor/src/github.py:122-132`, `executor/src/worker.py:424`]
- [x] [Review][Patch] Limpeza da condicional ternária redundante para endpoint GraphQL [`executor/src/github.py:267`]

---

## Dev Notes

### Guardrails de Arquitetura & Invariantes

- **AD-4 (Integração com GitHub é Propriedade Exclusiva do Executor):**
  - Apenas o `ai-dev-executor` realiza mutações na API do GitHub (criação de PRs, push de branches, atualização de status de cards no Projects v2).
  - Nenhum outro microsserviço (`ai-dev-api`, `ai-dev-notifications`) interage diretamente com mutações do GitHub.
- **AD-6 (Sandbox Docker Efêmero e Isolamento de Git):**
  - O código trabalhado no sandbox deve ser enviado para um branch de feature/story dedicado (ex: `aidev/story-3.2`), nunca commitando diretamente no branch `main`.
- **AD-8 (Memória Hierárquica em Três Níveis):**
  - Os links e metadados do PR aberto devem ser sincronizados em Nível 2 (`agent_memory` no PostgreSQL) e Nível 3 (`.memlog.md` no workspace via `fcntl.flock`).
- **Zero Deferred Work Policy (Enforcement):**
  - O corpo do PR deve explicitar que o código passou pelo Code Review interno com 0 débitos pendentes e 100% de validação local aprovada.

### Template Padrão do Corpo Semântico de Pull Request

```markdown
## 🤖 AI Developer — Pull Request de Entrega

### 📋 Contexto da História
- **História:** {{story_id}} — {{story_title}}
- **Card no GitHub Projects:** {{project_card_ref}}
- **Status do Workflow:** Concluído com Sucesso

### 🛠️ Resumo das Alterações
{{summary_bullets}}

### 🔍 Auto-Auditoria e Code Review Interno (Política Zero Deferred Work)
- **Status da Revisão:** {{review_status}}
- **Achados Identificados:** {{findings_count}}
- **Patches Aplicados:** {{patches_applied}}
- **Débitos Diferidos:** 0 (Conforme política de zero débitos)

### 🧪 Evidências de Validação Local
- **Testes Unitários / Linters:** {{passed_tests}} aprovados / {{failed_tests}} falhas
- **Comandos Executados:**
{{validation_command_logs}}

---
*Este Pull Request foi gerado e validado de forma autônoma pelo AI Developer e está pronto para a revisão humana final.*
```

### Arquivos Modificados / Criados Previstos

| Arquivo | Ação | Responsabilidade |
| --- | --- | --- |
| `executor/src/config.py` | UPDATE | Adicionar configurações do GitHub (`GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `GITHUB_API_URL`, etc.) |
| `executor/src/github.py` | NEW | Implementar `GitHubClient` para REST (PRs) e GraphQL (Projects v2) |
| `executor/src/worker.py` | UPDATE | Integrar etapa pós-validação de criação de PR e atualização de cards no Projects |
| `executor/src/memory.py` | UPDATE | Suporte a metadados de PR no `agent_memory` e `.memlog.md` |
| `tests/executor/test_github.py` | NEW | Testes unitários do cliente GitHub com mocks HTTP |
| `tests/executor/test_worker.py` | UPDATE | Testes de integração do worker cobrindo criação de PR e auditoria |

### Previous Story Intelligence (Story 3.1 & Story 2.3)

- **Fases Sequenciais:** A Story 3.1 estabeleceu a execução de `coding` seguido de `review` e validação local (`ValidationPipeline`).
- **Validação Local:** A Story 2.3 e 3.1 garantiram que o evento só é finalizado como sucesso se todos os comandos de validação retornarem `passed == True`.
- **Concorrência Segura em `.memlog.md`:** Qualquer escrita em `.memlog.md` utiliza `fcntl.flock` e deve ser executada em thread assíncrona (`asyncio.to_thread`) para evitar bloqueio do event loop.
- **Idempotência no PostgreSQL:** Gravação em `agent_memory` com `event_id` garantindo UPSERT sem duplicatas em retries.

### Git Intelligence

- **Últimos Commits:**
  - `36ff1af`: feat(executor): implement autonomous dev and internal code review workflow (Story 3.1)
  - `a72ed1b`: feat: add fcntl.flock to memlog file writes for multiprocess concurrency and update sprint status
  - `f9b1e05`: fix(story-2.3): resolucao dos itens deferidos F5 (idempotencia) e F6 (race condition)

---

## Dev Agent Record

### Agent Model Used

Gemini 3.7 Flash

### Debug Log References

- Suíte completa de testes executada com sucesso: 107 passed em 7.34s (`.venv/bin/pytest`)
- Testes unitários do GitHubClient em `tests/executor/test_github.py`: 10 passed
- Testes de integração e audit logs do worker em `tests/executor/test_worker.py`: 13 passed
- Testes de persistência de memória hierárquica em `tests/executor/test_memory.py`: 8 passed
- Testes de configuração em `tests/unit/test_config.py`: 5 passed

### Completion Notes List

- ✅ Implementação de `ExecutorSettings` com campos de integração do GitHub (`GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `GITHUB_API_URL`, `GITHUB_BASE_BRANCH`, `GITHUB_PROJECT_ID`, `GITHUB_DRY_RUN`).
- ✅ Criação do módulo `executor/src/github.py` contendo `GitHubClient`, `GitHubAPIError`, `GitHubAuthError`, formatação semântica de Markdown (com aderência a Conventional Commits e política *Zero Deferred Work*), abertura de PR via REST API v3 e mutação no Projects v2 via GraphQL.
- ✅ Integração do fluxo de publicação no `ExecutorWorker` pós-validação aprovada (`validation_passed == True`), emitindo logs de auditoria `PR_CREATION_STARTED`, `PR_CREATED`, `PROJECTS_CARD_UPDATED` e `PR_FAILED` em caso de erro com rollback/retry seguro (`fail_event`).
- ✅ Atualização da memória hierárquica (Nível 2 no PostgreSQL e Nível 3 no `.memlog.md`) com links e metadados estruturados do PR.
- ✅ 100% dos testes unitários e de integração aprovados sem regressões (107/107).

### File List

- `executor/src/config.py` (UPDATE)
- `executor/src/github.py` (NEW)
- `executor/src/memory.py` (UPDATE)
- `executor/src/worker.py` (UPDATE)
- `tests/unit/test_config.py` (UPDATE)
- `tests/executor/test_github.py` (NEW)
- `tests/executor/test_memory.py` (UPDATE)
- `tests/executor/test_worker.py` (UPDATE)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (UPDATE)
- `_bmad-output/implementation-artifacts/3-2-geracao-e-abertura-semantica-de-pull-requests-para-revisao-humana.md` (UPDATE)

### Change Log

- 2026-08-15: Implementação da História 3.2: Geração e Abertura Semântica de Pull Requests para Revisão Humana. Todos os critérios de aceite (AC 1 a 6) foram satisfeitos e validados com 100% de cobertura de testes.


