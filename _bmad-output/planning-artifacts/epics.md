---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-AI Developer-2026-08-08/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-AI Developer-2026-08-09/ARCHITECTURE-SPINE.md
---

# AI Developer - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for AI Developer, decomposing the requirements from the PRD, UX Design if it exists, and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: O sistema deve sincronizar itens do GitHub Projects v2 com cards de PRD, épicos, histórias e PRs.
FR2: O sistema deve iniciar uma execução quando um card for movido para "Ready for AI Dev".
FR3: O sistema deve armazenar todos os eventos recebidos por webhook na API do AIDEV (`ai-dev-api`).
FR4: O sistema deve consumir eventos e rotear cada um para o workflow apropriado.
FR5: O workflow de desenvolvimento deve receber a história como input e executar a revisão inicial do agente sem abrir PR.
FR6: O workflow de code review deve abrir uma PR para revisão humana ao final do processo.
FR7: Cada execução deve ocorrer em um container Docker isolado.
FR8: O sistema deve executar testes, linters e validações antes de abrir um PR.
FR9: O sistema deve registrar e tratar falhas de CI com um máximo de 2 a 3 tentativas.
FR10: O sistema deve movimentar cards para "Needs Human Action" quando necessário.
FR11: O sistema deve notificar por Telegram quando houver intervenção humana ou bloqueio.
FR12: O sistema deve manter a documentação no contexto da história ou do card do GitHub Projects.
FR13: O sistema deve manter uma memória persistente de resumos diários da jornada do agente.

### NonFunctional Requirements

NFR1: Segurança - O agente deve operar com permissões mínimas, sem acesso irrestrito a repositórios e segredos.
NFR2: Auditabilidade - Toda ação relevante deve gerar logs estruturados com contexto da história, do evento, do workflow e do resultado.
NFR3: Isolamento - Cada execução deve acontecer em container Docker efêmero, sem depender do estado do host.
NFR4: Confiabilidade - O agente deve tolerar falhas transitórias e encerrar com estado claro quando houver bloqueio.
NFR5: Observabilidade - O sistema deve permitir acompanhar o estado da execução em tempo real por logs e eventos.
NFR6: Manutenibilidade - O fluxo deve ser modular o suficiente para permitir expansão para novos workflows e integrações.

### Additional Requirements

- AD-1 (Persistência de Webhook): Validação e persistência atômica de todo evento de webhook no PostgreSQL (`ai-dev-api`) com status `PENDING` antes da execução.
- AD-2 (Consumo via PostgreSQL): Consumo de eventos `PENDING` diretamente do PostgreSQL pelos workers (`ai-dev-executor` e `ai-dev-notifications`) usando trava `SKIP LOCKED`.
- AD-3 (Idempotência): Garantia de idempotência no consumo de eventos via `event_id` ou hash de payload.
- AD-4 (Propriedade do GitHub): Apenas o componente `ai-dev-executor` realiza mutações na API do GitHub (Issues, PRs, Projects).
- AD-5 (Notificações HITL): Notificações derivadas do estado do evento; `ai-dev-notifications` consome eventos do PostgreSQL e envia alertas via Telegram.
- AD-6 (Sandbox Docker Efêmero): Execução em sandbox Docker efêmero com checkout isolado, validações locais (testes/linters) e teardown ao final.
- AD-7 (Política de Retry de CI): No máximo 3 tentativas de correção automática de falhas de CI antes de pausar o workflow e notificar para ação humana (`Needs Human Action`).
- AD-8 (Memória Hierárquica): Sistema de memória dos agentes em 3 níveis (sessão efêmera, histórico de eventos no PostgreSQL e conhecimento de longo prazo em tabelas/arquivos `project-context.md` e `.memlog.md`).
- AD-9 (Extensibilidade do Executor): Injeção dinâmica no sandbox de servidores/ferramentas MCP, Skills localizadas (`.agents/skills/`) e Templates de Prompts.
- AD-10 (Empacotamento OCI/Docker): Todos os serviços (`ai-dev-api`, `ai-dev-executor`, `ai-dev-notifications`, `ai-dev-migrations`) entregues como imagens OCI/Docker imutáveis.

### UX Design Requirements

*Nenhum documento de contrato de UX Design (DESIGN.md / EXPERIENCE.md) foi encontrado no repositório.*

### FR Coverage Map

- **FR1:** Épico 3 (Story 3.1, Story 3.2 via MCP / gh CLI)
- **FR2:** Épico 1 (Story 1.2)
- **FR3:** Épico 1 (Story 1.2)
- **FR4:** Épico 1 (Story 1.3)
- **FR5:** Épico 2 & Épico 3 (Story 2.1, Story 3.1)
- **FR6:** Épico 3 (Story 3.2)
- **FR7:** Épico 2 (Story 2.1)
- **FR8:** Épico 2 (Story 2.3)
- **FR9:** Épico 4 (Story 4.1)
- **FR10:** Épico 4 (Story 4.2)
- **FR11:** Épico 4 (Story 4.3)
- **FR12:** Épico 1 & Épico 3 (Story 1.2, Story 3.1, Story 3.2)
- **FR13:** Épico 2 (Story 2.3)

## Epic List

### Epic 1: Ingestão de Webhooks, Armazenamento e Roteamento de Eventos (Event Core & Ingestion)
O desenvolvedor/sistema possui um serviço HTTP confiável (`ai-dev-api`) e event store (`PostgreSQL`) capaz de receber, validar, persistir e rotear de forma atômica e idempotente todos os webhooks do GitHub (transições de status, eventos de CI, comentários).
**FRs cobertos:** FR2, FR3, FR4, FR12

### Epic 2: Orquestração de Execução e Sandbox Isolado do Agente (Autonomous Execution Sandbox)
O agente de desenvolvimento (`ai-dev-executor`) consome eventos elegíveis do PostgreSQL via trava de registro (`SKIP LOCKED`), inicializando um sandbox Docker efêmero com injeção de MCPs, Skills e Prompts para realizar alterações no código, executar testes/linters locais e manter memória hierárquica diária.
**FRs cobertos:** FR5, FR7, FR8, FR13

### Epic 3: Workflow de Desenvolvimento Autônomo, Code Review e Abertura de PRs (Autonomous Dev & PR Automation)
O sistema orquestra as fases de desenvolvimento e code review interno no sandbox efêmero via agente autônomo (munido de MCPs e CLI `gh`), gerando e abrindo Pull Requests semânticos validados para revisão humana e sincronizando o status dos cards no GitHub Projects v2.
**FRs cobertos:** FR1, FR5, FR6, FR12

### Epic 4: Resiliência de CI, Notificações HITL e Gestão de Intervenção Humana (CI Auto-Healing & HITL Notifications)
O sistema monitora o status de builds e falhas de CI no GitHub, tentando correções automáticas no sandbox (até o limite de 3 tentativas) e notificando desenvolvedores via Telegram (`ai-dev-notifications`) quando houver bloqueios ou necessidade de intervenção humana (movendo cards para "Needs Human Action").
**FRs cobertos:** FR9, FR10, FR11

---

## Epic 1: Ingestão de Webhooks, Armazenamento e Roteamento de Eventos (Event Core & Ingestion)

O desenvolvedor/sistema possui um serviço HTTP confiável (`ai-dev-api`) e event store (`PostgreSQL`) capaz de receber, validar, persistir e rotear de forma atômica e idempotente todos os webhooks do GitHub.

### Story 1.1: Schema do Event Store e Migrações em PostgreSQL (`ai-dev-migrations`)

As a desenvolvedor do AIDEV,
I want um esquema de banco de dados PostgreSQL com tabelas de eventos, status, payloads e histórico de auditoria empacotados em um utilitário de migração,
So that o sistema possa registrar o estado dos eventos de forma persistente, estruturada e versionada.

**Acceptance Criteria:**

**Given** um banco de dados PostgreSQL zerado ou desatualizado
**When** a imagem de migração `ai-dev-migrations` for executada
**Then** a tabela de eventos (contendo `id`, `event_id`, `event_type`, `status`, `payload`, `created_at`, `updated_at`) e a tabela de auditoria/memória devem ser criadas com índices apropriados
**And** o status inicial dos eventos deve aceitar o valor padrão `PENDING`.

### Story 1.2: Endpoint de Recepção, Validação e Ingestão de Webhooks (`ai-dev-api`)

As a sistema AIDEV,
I want um serviço FastAPI (`ai-dev-api`) que receba e valide webhooks assinados do GitHub e persista o payload no PostgreSQL,
So that nenhum evento enviado pelo GitHub (como movimentação para "Ready for AI Dev") seja perdido ou processado sem validação de segurança.

**Acceptance Criteria:**

**Given** um evento enviado pelo GitHub via requisição HTTP POST para `/webhooks/github`
**When** o webhook possuir assinatura secreta válida (`X-Hub-Signature-256`)
**Then** a API deve classificar o `event_type`, gravar o evento no PostgreSQL com status `PENDING` e responder HTTP 202 Accepted
**And** se a assinatura for inválida ou o payload for malformatado, a API deve rejeitar a requisição com HTTP 401/400 sem salvar no banco.

### Story 1.3: Roteamento e Consumo Idempotente via Trava de Banco (`SKIP LOCKED`)

As a worker do AIDEV,
I want consumir eventos em status `PENDING` diretamente do PostgreSQL filtrando por tipo de evento e aplicando trava de registro,
So that eventos concorrentes ou duplicados sejam processados exatamente uma vez sem necessidade de um broker intermediário.

**Acceptance Criteria:**

**Given** múltiplos eventos gravados na tabela do PostgreSQL com status `PENDING`
**When** um worker (`ai-dev-executor` ou `ai-dev-notifications`) consultar novos eventos elegíveis
**Then** a consulta deve utilizar `FOR UPDATE SKIP LOCKED` para selecionar e marcar a linha atomicamente com o status `PROCESSING`
**And** tentativas de reprocessamento do mesmo `event_id` ou hash de payload idêntico devem ser identificadas e tratadas de forma idempotente sem colateral repetido.

### Story 1.4: Adição da Coluna Repository no Event Store e Resolução de Webhooks

As a sistema AIDEV,
I want que a tabela de eventos do PostgreSQL possua uma coluna dedicada `repository` e que o endpoint de webhooks resolva o repositório alvo (inclusive consultando o GitHub GraphQL para eventos de Projects v2) antes de persistir o evento,
So that todos os eventos no Event Store possuam um repositório alvo válido e garantido, viabilizando consumo multi-repo e eliminando falhas tardias no worker.

**Acceptance Criteria:**

**Given** um webhook recebido no endpoint `POST /webhooks/github`
**When** a requisição for processada
**Then** a API deve extrair o `repository` diretamente do payload ou via consulta GraphQL (`node(id: $content_node_id)`) para itens de Projects v2 (`Issue`/`PullRequest`), gravando na coluna `repository` da tabela `events` com migration Alembic
**And** rejeitar eventos órfãos/DraftIssues sem repositório com HTTP 422 Unprocessable Entity.

---

## Epic 2: Orquestração de Execução e Sandbox Isolado do Agente (Autonomous Execution Sandbox)

O agente de desenvolvimento (`ai-dev-executor`) consome eventos elegíveis do PostgreSQL via trava de registro, inicializando um sandbox Docker efêmero com injeção de MCPs, Skills e Prompts para realizar alterações no código, executar testes/linters locais e manter memória hierárquica diária.

### Story 2.1: Worker de Orquestração do Executor e Sandbox Docker Efêmero (`ai-dev-executor`)

As a sistema AIDEV,
I want um worker em Python que inicialize e destrua um container Docker efêmero para cada evento de execução consumido do PostgreSQL,
So that qualquer alteração de código ou execução de testes ocorra em um ambiente isolado, reproduzível e descartável.

**Acceptance Criteria:**

**Given** um evento de execução assumido pelo worker `ai-dev-executor`
**When** o fluxo de desenvolvimento for iniciado
**Then** um container Docker efêmero deve ser instanciado com o código do repositório clonado em um volume temporário
**And** ao final da execução (sucesso ou falha), o container deve sofrer teardown completo garantindo zero contaminação no host.

### Story 2.2: Injeção Dinâmica de Contexto (MCPs, Skills e Prompts)

As a agente AI Developer,
I want ter acesso às ferramentas MCP configuradas, Skills localizadas no repositório (`.agents/skills/`) e Templates de Prompts versionados dentro do sandbox,
So that minhas ações de código e planejamento respeitem rigorosamente a arquitetura e os padrões do projeto.

**Acceptance Criteria:**

**Given** um container sandbox inicializado para uma história de usuário
**When** a sessão da engine LLM for preparada
**Then** o ambiente deve injetar os servidores MCP disponíveis, carregar as Skills presentes no caminho `.agents/skills/` e carregar o template de prompt correspondente à fase (código/revisão)
**And** a execução deve falhar com aviso claro caso um prompt template obrigatório esteja ausente.

### Story 2.3: Pipeline de Validação Local (Testes/Linters) e Memória Hierárquica Diária

As a engenheiro de software,
I want que o agente execute a suíte de testes e linters dentro do sandbox e registre os resumos de progresso no PostgreSQL e em arquivo `.memlog.md`,
So that alterações incorretas sejam bloqueadas antes da entrega e a memória do agente permaneça atualizada.

**Acceptance Criteria:**

**Given** alterações de código realizadas pelo agente no sandbox
**When** o ciclo de validação pré-entrega for acionado
**Then** os linters e testes unitários definidos para o projeto (ex: Java ou Flutter) devem ser executados localmente dentro do container
**And** um resumo diário da jornada do agente deve ser persistido na tabela de memória de longo prazo no PostgreSQL e sincronizado no repositório em `.memlog.md`.

---

## Epic 3: Workflow de Desenvolvimento Autônomo, Code Review e Abertura de PRs (Autonomous Dev & PR Automation)

O sistema orquestra as fases de desenvolvimento e code review interno no sandbox efêmero via agente autônomo (munido de MCPs e CLI `gh`), gerando e abrindo Pull Requests semânticos validados para revisão humana e sincronizando o status dos cards no GitHub Projects v2.

### Story 3.1: Workflow de Desenvolvimento Autônomo e Code Review sem PR Precoce

As a agente AI Developer,
I want executar o workflow de desenvolvimento e em seguida o workflow interno de code review antes de abrir a Pull Request pública,
So that propostas de código brutas sejam refatoradas e auto-auditadas antes de solicitar atenção humana.

**Acceptance Criteria:**

**Given** um evento de história movida para "Ready for AI Dev"
**When** o worker executar a primeira fase de desenvolvimento no sandbox
**Then** o agente deve aplicar as modificações no código, executar a revisão interna de regras e critérios de aceite no sandbox sem abrir PR pública prematura
**And** o resultado do code review interno deve ser anexado aos registros do evento no banco de dados e na memória do agente.

### Story 3.2: Geração e Abertura Semântica de Pull Requests para Revisão Humana

As a revisor humano,
I want receber um Pull Request estruturado no GitHub com a descrição clara das alterações, contexto da história e evidências das validações locais (via `gh` CLI / GitHub MCP),
So that eu possa realizar a revisão de código final com agilidade e rastreabilidade.

**Acceptance Criteria:**

**Given** a conclusão bem-sucedida do workflow de code review interno no sandbox
**When** a etapa de publicação for alcançada
**Then** o `ai-dev-executor` deve orquestrar o push do branch e a abertura de uma Pull Request no GitHub contendo título semântico, corpo formatado com resumo das mudanças, testes executados e link para o card original
**And** o evento deve ser atualizado para status `COMPLETED` e o card correspondente atualizado no GitHub Projects v2.

---

## Epic 4: Resiliência de CI, Notificações HITL e Gestão de Intervenção Humana (CI Auto-Healing & HITL Notifications)

O sistema monitora o status de builds e falhas de CI no GitHub, tentando correções automáticas no sandbox (até o limite de 3 tentativas) e notificando desenvolvedores via Telegram (`ai-dev-notifications`) quando houver bloqueios ou necessidade de intervenção humana (movendo cards para "Needs Human Action").

### Story 4.1: Monitoramento de Webhooks de CI e Ciclo de Autocorreção (Até 3 Tentativas)

As a agente AI Developer,
I want receber eventos de falha de build/CI do GitHub Actions e disparar rodadas automáticas de correção no sandbox efêmero,
So that quebras simples de integração sejam corrigidas de forma autônoma sem requerer ação humana imediata.

**Acceptance Criteria:**

**Given** uma falha de CI reportada via webhook em um PR aberto pelo agente
**When** a contagem de tentativas de correção para a história for menor que 3 (ex: tentativas 1, 2 ou 3)
**Then** o evento de reparo deve ser agendado no PostgreSQL, abrindo um sandbox efêmero para analisar o log de erro do CI e commitar a correção no branch do PR
**And** o número de tentativas executadas deve ser incrementado no registro do evento.

### Story 4.2: Transição de Estado para "Needs Human Action" e Bloqueio Seguro

As a desenvolvedor líder,
I want que o sistema interrompa o ciclo autônomo e mova o card para "Needs Human Action" se a falha persistir após 3 tentativas ou se houver ambiguidade,
So that o sistema nunca entre em loop infinito ou aplique alterações destrutivas sem aprovação.

**Acceptance Criteria:**

**Given** uma falha de CI que atingiu o limite máximo de 3 tentativas OU uma situação de incerteza de requisitos
**When** a validação de limite for avaliada pelo executor
**Then** o card no GitHub Projects v2 deve ser movido para o status "Needs Human Action", a execução deve ser pausada e um log de bloqueio com contexto completo deve ser gravado.

### Story 4.3: Worker de Notificações Telegram e Alertas HITL (`ai-dev-notifications`)

As a desenvolvedor humano,
I want um serviço dedicado (`ai-dev-notifications`) que consuma eventos de notificação do PostgreSQL e envie alertas no Telegram com botões/links diretos,
So that eu seja avisado imediatamente quando o agente precisar de ajuda humana ou concluir um marco importante.

**Acceptance Criteria:**

**Given** um evento de bloqueio "Needs Human Action" ou marco relevante gravado no PostgreSQL
**When** o worker `ai-dev-notifications` consumir o evento em status `PENDING`
**Then** uma mensagem formatada deve ser enviada para o grupo/chat configurado no Telegram via Bot API, contendo resumo do problema, link da história/PR e instrução de ação
**And** a mensagem de notificação enviada deve ser registrada com sucesso no banco de dados.

