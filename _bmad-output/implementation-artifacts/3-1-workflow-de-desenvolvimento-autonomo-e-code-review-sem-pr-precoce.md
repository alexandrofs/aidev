---
baseline_commit: a72ed1bc9645c554fa16bb9b77ddde22da844310
---

# Story 3.1: Workflow de Desenvolvimento Autônomo e Code Review sem PR Precoce

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a agente AI Developer,
I want executar o workflow de desenvolvimento e em seguida o workflow interno de code review antes de abrir a Pull Request pública,
so that propostas de código brutas sejam refatoradas e auto-auditadas antes de solicitar atenção humana.

## Acceptance Criteria

1. **Orquestração Sequencial Autônoma de Fases (Coding → Review) no Sandbox Efêmero (AC: 1)**
   - **Given** um evento de execução de história (`workflow.execution` ou evento associado a card em "Ready for AI Dev") reivindicado pelo `ExecutorWorker`
   - **When** o ciclo de execução for iniciado
   - **Then** o worker deve orquestrar sequencialmente no sandbox efêmero a fase de desenvolvimento (`coding` via prompt template e contexto com `bmad-dev-story`) seguida imediatamente pela fase de revisão interna (`review` via prompt template e contexto com `bmad-code-review`)
   - **And** nenhuma Pull Request pública deve ser aberta prematuramente durante este ciclo no GitHub.

2. **Auditoria e Validação dos Critérios de Aceite no Code Review Interno (AC: 2)**
   - **Given** as modificações de código realizadas na fase de desenvolvimento dentro do container
   - **When** a fase de revisão de código (`review`) for executada
   - **Then** o agente deve auditar o código contra as regras arquiteturais, convenções do projeto e critérios de aceite especificados na história
   - **And** a política *Zero Deferred Work* deve ser aplicada estritamente: todos os problemas identificados (patches) devem ser corrigidos na própria sessão de review sem deixar débitos diferidos.

3. **Integração com o Pipeline de Validação Local Pré-Entrega (AC: 3)**
   - **Given** o código refatorado e auditado pelo code review interno
   - **When** o `ValidationPipeline` for acionado ao término das fases
   - **Then** a suíte de testes e linters configurada deve ser executada localmente no sandbox garantindo 100% de aprovação e zero regressões
   - **And** se o code review ou a validação local falhar, o evento deve registrar o log de auditoria `CODE_REVIEW_FAILED` ou `VALIDATION_FAILED` e ser marcado com falha sem abrir PR.

4. **Registro Estruturado dos Resultados do Code Review no PostgreSQL e `.memlog.md` (AC: 4)**
   - **Given** a conclusão da fase de code review (com ou sem correções aplicadas)
   - **When** a etapa de sincronização de memória hierárquica for executada pelo `AgentMemoryManager`
   - **Then** o resumo estruturado contendo status do review, patches aplicados, testes executados e decisões tomadas deve ser persistido na tabela `agent_memory` (Nível 2) com UPSERT idempotente
   - **And** o arquivo `.memlog.md` na raiz do workspace (Nível 3) deve ser atualizado com append formatado via file lock seguro (`fcntl.flock`), anexando o registro completo da revisão interna.

5. **Registro de Logs de Auditoria e Preparação para Publicação de PR (AC: 5)**
   - **Given** a aprovação completa do workflow interno (desenvolvimento + code review + validação de testes)
   - **When** o evento for finalizado no `EventRepository`
   - **Then** os logs de auditoria `WORKFLOW_PHASE_COMPLETED` (para cada fase), `CODE_REVIEW_PASSED` e `VALIDATION_PASSED` devem ser gravados na tabela `audit_logs`
   - **And** o evento deve ser atualizado com os detalhes estruturados das fases e o estado de prontidão para a etapa subsequente de abertura semântica de Pull Request (História 3.2).

6. **Suíte de Testes Automatizados (Unitários e de Integração) (AC: 6)**
   - **Given** os novos fluxos de desenvolvimento autônomo e code review interno no `ExecutorWorker`
   - **When** a suíte de testes for executada com `pytest`
   - **Then** testes unitários e de integração em `tests/executor/` devem cobrir:
     - Execução encadeada das fases `coding` e `review` com injeção de seus respectivos bundles de contexto
     - Garantia de que nenhuma chamada externa de abertura de PR prematuro ocorra durante a história 3.1
     - Tratamento de falhas e interrupção graciosa caso a fase de review ou desenvolvimento falhe
     - Persistência estruturada do relatório de review em `agent_memory` e `.memlog.md`
     - 100% de aprovação em toda a suíte de testes sem regressões.

---

## Tasks / Subtasks

- [x] Task 1: Ajuste e Padronização dos Templates de Prompts (`executor/prompts/`) (AC: 1, 2)
  - [x] Revisar `executor/prompts/coding.md` para garantir instruções claras de implementação guiada por BDD e TDD com `bmad-dev-story`
  - [x] Ajustar `executor/prompts/review.md` para focar estritamente na auditoria interna de código, aplicação imediata de patches (*Zero Deferred Work*), validação de regras arquiteturais e isolamento de PR (sem abrir PR nesta fase)
  - [x] Adicionar testes de validação dos prompts em `tests/executor/test_context_loader.py`

- [x] Task 2: Implementação da Orquestração Multi-Fase no `ExecutorWorker` (`executor/src/worker.py`) (AC: 1, 2, 5)
  - [x] Garantir que o payload de evento defina o fluxo padrão de fases: `phases=["coding", "review"]` quando iniciado a partir de cards em "Ready for AI Dev"
  - [x] Implementar execução sequencial das fases com compilação e injeção dinâmica de `context_bundle` específico para cada fase (`coding` e `review`)
  - [x] Registrar logs de auditoria `WORKFLOW_PHASE_STARTED` e `WORKFLOW_PHASE_COMPLETED` para cada fase no `EventRepository`
  - [x] Adicionar captura e agregação estruturada de métricas de review (patches aplicados, achados resolvidos, status de aprovação)

- [x] Task 3: Integração do Code Review com a Memória Hierárquica e Auditoria (`executor/src/memory.py` e `executor/src/worker.py`) (AC: 4, 5)
  - [x] Estender o schema de resumo em `AgentMemoryManager` para incluir metadados detalhados do Code Review (`review_status`, `patches_applied`, `criteria_evaluated`)
  - [x] Garantir gravação atômica e idempotente na tabela `agent_memory` no PostgreSQL (Nível 2)
  - [x] Garantir append formatado e seguro no `.memlog.md` via `fcntl.flock` com seções destacando a auto-auditoria e refatoração realizada (Nível 3)
  - [x] Registrar audit log `CODE_REVIEW_PASSED` (ou `CODE_REVIEW_FAILED` em caso de erro/reprovação)

- [x] Task 4: Configuração e Flags de Execução (`executor/src/config.py`) (AC: 1)
  - [x] Adicionar suporte em `ExecutorSettings` para fases padrão (`DEFAULT_WORKFLOW_PHASES: list[str] = ["coding", "review"]`)
  - [x] Garantir que o branch de trabalho seja isolado no container sem mutação direta em branch de produção

- [x] Task 5: Suíte de Testes Automatizados (AC: 6)
  - [x] Criar testes em `tests/executor/test_worker_workflow.py` (ou atualizar `tests/executor/test_worker.py`) cobrindo o ciclo completo `coding` → `review`
  - [x] Testar cenários de sucesso: desenvolvimento autônomo + review aprovado + validação de testes + memória atualizada
  - [x] Testar cenários de falha: erro na fase de coding, erro/reprovação na fase de review, falha de injeção de contexto
  - [x] Testar isolamento garantindo que nenhum PR externo seja chamado prematuramente
  - [x] Executar `.venv/bin/pytest` para validar 100% de sucesso em toda a suíte (87+ testes)

---

## Dev Notes

### Guardrails de Arquitetura & Invariantes

- **AD-4 (Integração com GitHub é Propriedade do Executor):**
  - O agente executor é o único componente responsável por efeitos colaterais. Na **História 3.1**, o escopo restringe-se ao desenvolvimento autônomo e auto-auditoria/review interno no sandbox. A abertura física de Pull Request e atualização de cards no GitHub Projects v2 é responsabilidade da **História 3.2**. Não deve haver criação de PR precoce na 3.1.
- **AD-6 (Sandbox Docker Efêmero):**
  - As fases de `coding` e `review` rodam dentro do container Docker efêmero gerenciado por `DockerSandboxManager`, com checkout limpo e teardown garantido.
- **AD-8 (Memória Hierárquica em 3 Níveis):**
  - **Nível 1:** Contexto efêmero de prompt injetado no container para cada fase.
  - **Nível 2:** Histórico persistido em `agent_memory` e `audit_logs` no PostgreSQL com UPSERT idempotente (`event_id`).
  - **Nível 3:** Registro durável no `.memlog.md` na raiz do workspace com file lock (`fcntl.flock`).
- **AD-9 (Extensibilidade do Executor via MCPs, Skills e Prompts):**
  - Na fase `coding`, o contexto deve conter `coding.md` e referenciar `bmad-dev-story`.
  - Na fase `review`, o contexto deve conter `review.md` e referenciar `bmad-code-review`.
- **Zero Deferred Work Policy (Retrospectiva Épico 1 & 2):**
  - A fase de code review não deve diferir achados como `defer`. Todos os problemas identificados devem ser corrigidos na própria sessão de review antes da conclusão da história.

### Estrutura de Metadados do Resumo de Memória (Nível 2 e Nível 3)

```json
{
  "title": "Story 3.1: Workflow de Desenvolvimento Autônomo e Code Review sem PR Precoce",
  "status": "COMPLETED",
  "actions": [
    "Fase Coding: Implementação de lógica e testes com bmad-dev-story",
    "Fase Review: Auditoria interna com bmad-code-review e correção de achados",
    "Validação Local: Execução de pytest e linters"
  ],
  "review_summary": {
    "status": "APPROVED",
    "findings_count": 2,
    "patches_applied": 2,
    "deferred_count": 0
  },
  "test_results": {
    "passed": 87,
    "failed": 0
  },
  "decisions": "Código auto-auditado com sucesso e aprovado para posterior abertura de PR."
}
```

### Arquivos Modificados / Criados Previstos

| Arquivo | Ação | Responsabilidade |
| --- | --- | --- |
| `executor/prompts/review.md` | UPDATE | Alinhar prompt de review para auto-auditoria sem abertura precoce de PR |
| `executor/prompts/coding.md` | UPDATE | Reforçar diretrizes de implementação autônoma e TDD |
| `executor/src/config.py` | UPDATE | Configuração `DEFAULT_WORKFLOW_PHASES = ["coding", "review"]` |
| `executor/src/worker.py` | UPDATE | Orquestração do ciclo multi-fase `coding` → `review` com auditoria e validação |
| `executor/src/memory.py` | UPDATE | Suporte a metadados enriquecidos de code review no `.memlog.md` |
| `tests/executor/test_worker.py` | UPDATE | Testes do fluxo de desenvolvimento autônomo e review interno |
| `tests/executor/test_context_loader.py` | UPDATE | Validação dos prompts atualizados |

---

## Dev Agent Record

### Agent Model Used
- Gemini 3.7 Flash

### Debug Log References
- Execução da suíte completa de testes: 91 testes passando (100% de sucesso).
- Validação do fluxo multi-fase padrão `coding` -> `review` -> validação local.
- Validação de audit logs: `WORKFLOW_PHASE_STARTED`, `WORKFLOW_PHASE_COMPLETED`, `CODE_REVIEW_PASSED`, `CODE_REVIEW_FAILED`, `VALIDATION_PASSED`, `VALIDATION_FAILED`.

### Completion Notes List
- ✅ **Task 1:** Templates de prompts em `executor/prompts/coding.md` e `executor/prompts/review.md` atualizados com diretrizes de BDD/TDD (`bmad-dev-story`), auditoria interna (`bmad-code-review`), aplicação obrigatória de patches (*Zero Deferred Work*) e isolamento de PR (sem abertura precoce de Pull Request).
- ✅ **Task 2 & 4:** Configurada lista de fases padrão `DEFAULT_WORKFLOW_PHASES = ["coding", "review"]` em `ExecutorSettings`. Implementada execução sequencial multi-fase no `ExecutorWorker` com emissão de logs `WORKFLOW_PHASE_STARTED` e `WORKFLOW_PHASE_COMPLETED`.
- ✅ **Task 3:** Integração da fase de Code Review com a memória hierárquica (Nível 2 em `agent_memory` e Nível 3 em `.memlog.md` via `fcntl.flock`), com estruturação de `review_summary` e emissão dos audit logs `CODE_REVIEW_PASSED` / `CODE_REVIEW_FAILED`.
- ✅ **Task 5:** Suíte de testes automatizados expandida e validada com 91 testes passando sem regressões.

### File List
- `executor/prompts/coding.md` (MODIFIED)
- `executor/prompts/review.md` (MODIFIED)
- `executor/src/config.py` (MODIFIED)
- `executor/src/worker.py` (MODIFIED)
- `executor/src/memory.py` (MODIFIED)
- `tests/executor/test_context_loader.py` (MODIFIED)
- `tests/executor/test_worker.py` (MODIFIED)
- `tests/executor/test_memory.py` (MODIFIED)

### Change Log
- 2026-08-13: Implementação completa da Story 3.1 - Workflow de Desenvolvimento Autônomo e Code Review sem PR Precoce.

