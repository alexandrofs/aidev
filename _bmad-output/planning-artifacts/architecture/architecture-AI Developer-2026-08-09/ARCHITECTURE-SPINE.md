---
name: 'AI Developer Architecture'
type: architecture-spine
purpose: build-substrate
altitude: feature
paradigm: 'orquestração orientada a eventos com fluxo de eventos persistido'
scope: 'agente autônomo AI Developer MVP'
status: final
created: 2026-08-09
updated: 2026-08-10
binds:
  - 'ingestão de webhook'
  - 'execução orientada a eventos'
  - 'integração com GitHub'
  - 'notificação HITL'
  - 'armazenamento de memória dos agentes'
  - 'empacotamento OCI/Docker de deployables'
sources:
  - '_bmad-output/planning-artifacts/prds/prd-AI Developer-2026-08-08/prd.md'
  - 'docs/brief.md'
companions: []
---

# Espinha de Arquitetura — AI Developer

## Paradigma de Design

Arquitetura enxuta orientada a eventos, com um fluxo canônico de eventos persistidos no PostgreSQL.
A solução separa:
- uma API leve de Webhook (`ai-dev-api`) que recebe, valida, classifica e persiste eventos externos do GitHub no PostgreSQL,
- um agente de execução (`ai-dev-executor`) que consome eventos de execução diretamente do PostgreSQL via trava de linha (`SKIP LOCKED`), orquestra o sandbox Docker e controla a integração com GitHub,
- um serviço de notificações (`ai-dev-notifications`) que consome eventos de notificação diretamente do PostgreSQL e entrega os alertas via Telegram.

Esse paradigma simplificado elimina intermediários mantendo o event store (PostgreSQL) como fonte única da verdade e barramento de eventos seguro com idempotência. 

## Invariantes e Regras

### AD-1 — Persistir todo evento de webhook antes de executar
- **Binds:** ingestão de webhook, event store, consumidor de execução
- **Prevents:** perda ou não rastreamento de payloads de webhook e acoplamento direto entre webhook e execução
- **Rule:** todos os payloads de webhook externos devem ser validados e persistidos atomica-mente antes de qualquer execução ou transição de workflow.

### AD-2 — Consumo de eventos persistidos direto por workers via PostgreSQL
- **Binds:** `api`, `executor`, `notifications`, event store (PostgreSQL)
- **Prevents:** necessidade de serviço intermediário de processamento (`processor`), acoplamento de comunicação inter-serviço e execuções concorrentes duplicadas
- **Rule:** os workers (`executor` e `notifications`) devem consumir eventos elegíveis em status `PENDING` diretamente do PostgreSQL filtrando por `event_type`, realizando o claim idempotente por trava de registro (ex: `SKIP LOCKED`) e registrando as transições de estado no banco.

### AD-3 — Controle de idempotência no consumo de eventos
- **Binds:** event store, processamento do consumidor, estado de workflow
- **Prevents:** reprocessamento duplicado do mesmo evento e efeitos colaterais repetidos
- **Rule:** o sistema deve identificar eventos únicos por `event_id` e/ou hash de payload e aplicar processamento idempotente, garantindo que cada evento persistido gere no máximo uma execução de ação por estado.

### AD-4 — Integração com GitHub Projects / Issues / PR é propriedade do agente de execução
- **Binds:** integração com API do GitHub, criação de PR, sincronização de cards, atualizações de issues
- **Prevents:** mutações GitHub dispersas entre serviços e estado de workflow inconsistente
- **Rule:** apenas o componente executor realiza efeitos colaterais no GitHub; outros serviços leem/escrevem intenções de workflow através do event store.

### AD-5 — Decisões de notificação derivam do estado do evento e são registradas centralmente
- **Binds:** metadados de notificação, estado de evento, ações HITL
- **Prevents:** múltiplos caminhos de notificação descoordenados e alertas humanos inconsistentes
- **Rule:** gatilhos de notificação devem ser armazenados na tabela de eventos ou em um fluxo de auditoria associado; o executor ou um consumidor dedicado pode enviar a mensagem.

### AD-6 — Cada execução é realizada em um sandbox de container efêmero
- **Binds:** agente de execução, controlador de container, pipeline de validação local
- **Prevents:** vazamento de estado do host, execuções não reproduzíveis e deriva de ambiente
- **Rule:** toda execução de código deve ocorrer em um sandbox Docker novo, com checkout isolado, execução de testes/linters e teardown ao final.

### AD-7 — Retentativas de correção de CI são limitadas e escaladas para revisão humana
- **Binds:** tratamento de falha de CI, política de retry, fluxo de escalonamento
- **Prevents:** loops infinitos de correção e reescritas automáticas inseguras
- **Rule:** a correção de falha de CI deve ser tentada no máximo 3 vezes antes que o evento seja marcado para revisão humana e o workflow pause.

### AD-8 — Armazenamento de memória dos agentes em modelo hierárquico em três níveis
- **Binds:** `executor`, `persistence/` (PostgreSQL), contexto do LLM e arquivos de repositório (`project-context.md`)
- **Prevents:** acoplamento indevido de estado em memória volátil de processo, vazamento de contexto entre execuções e perda de rastreabilidade de decisões e conhecimento
- **Rule:** a memória dos agentes deve ser mantida em 3 níveis: (1) Curto prazo efêmero durante a sessão de prompt no sandbox `executor`; (2) Estado de workflow, comandos, logs e histórico de eventos persistidos no `PostgreSQL` (event store); (3) Conhecimento persistente de longo prazo mantido em tabelas dedicadas de memória/conhecimento no `PostgreSQL` e sincronizado com arquivos de contexto do repositório (`project-context.md` e `.memlog.md`).

### AD-9 — Extensibilidade do executor via MCPs, Skills e Templates de Prompts
- **Binds:** `executor/`, sandbox Docker, engine LLM, clientes de ferramentas MCP e biblioteca de prompts
- **Prevents:** acoplamento rígido (*hardcoding*) de ferramentas e fluxos de agente, e falta de padronização na injeção de contexto/skills
- **Rule:** o executor deve injetar dinamicamente em cada sessão do sandbox: (1) Servidores e ferramentas MCP configurados para o ambiente; (2) Skills e customizações descobertas no repositório de destino (`.agents/skills/`); (3) Templates de prompts estruturados e versionados para as fases de planejamento, código e revisão.

### AD-10 — Empacotamento e entrega de todos os serviços como imagens OCI/Docker
- **Binds:** `api/`, `executor/`, `notifications/`, `persistence/` (migrations), pipeline CI/CD e infraestrutura de implantação
- **Prevents:** estratégias mistas não padronizadas de implantação (ex: misturar bare-metal com containers), inconsistência de ambientes de runtime e dependências implícitas no host
- **Rule:** todos os componentes implantáveis (`ai-dev-api`, `ai-dev-executor`, `ai-dev-notifications`, `ai-dev-migrations`) devem ser obrigatoriamente compilados e entregues como imagens OCI/Docker independentes, auto-contidas, imutáveis e configuradas via variáveis de ambiente.

## Convenções de Consistência

| Preocupação | Convenção |
| --- | --- |
| Nomenclatura (entidades, arquivos, interfaces, eventos) | `event_*` para eventos persistidos; `workflow_*` para estado de processamento; `GitHub*` para helpers de integração |
| Dados e formatos (ids, datas, formatos de erro, envelopes) | envelopes JSON; timestamps ISO 8601; campos `id`, `type`, `status`, `payload`, `created_at`, `updated_at` |
| Estado e cross-cutting (mutação, erros, logs, config, auth) | transições de estado persistidas por evento; logs estruturados com `event_id` / `workflow_id`; config por variáveis de ambiente; auth via tokens de serviço com escopo |

## Stack

| Nome | Versão |
| --- | --- |
| Python | 3.12 |
| FastAPI | 0.111 |
| PostgreSQL | 16 |
| Docker | 24 |
| GitHub REST/GraphQL API | v3 / GraphQL |
| Telegram Bot API | versão estável atual |

## Semente Estrutural

```text
{project-root}/
  api/                # receptor de webhook, validação de evento, classificação e persistência
  executor/           # consumidor de eventos de execução, orquestração de sandbox, integração GitHub
  persistence/        # esquema de evento, abstrações de repositório, logs de auditoria, migrações
  notifications/      # consumidor de eventos de notificação, integração Telegram/HITL
  infra/              # Dockerfiles, manifests compose, configuração de implantação e runtime
  tests/              # testes de integração e contrato para workflow e execução lógica
  docs/               # documentação de arquitetura, operação e implantação
```

## Diagrama de Containers

```mermaid
C4Container
    title AI Developer MVP - Diagrama de Containers
    Person_Ext(github, "GitHub", "Plataforma externa de Webhooks, Issues, PRs e Projects")
    Person_Ext(user, "Desenvolvedor / Reviewer", "Usuário humano recebendo notificações e interagindo via Telegram")

    System_Boundary(mvp, "AI Developer MVP") {
        Container(api, "ai-dev-api", "Python / FastAPI", "Recebe webhooks do GitHub, valida, rotula o tipo do evento e persiste no banco com status PENDING.")
        Container(executor, "ai-dev-executor", "Python worker", "Consome eventos de execução diretamente do banco via lock idempotente, orquestra sandbox Docker e interage com GitHub.")
        Container(notifications, "ai-dev-notifications", "Python worker", "Consome eventos de notificação diretamente do banco e entrega alertas via Telegram.")
        ContainerDb(db, "PostgreSQL", "Banco de dados / Event Store", "Armazena eventos, estado de workflow, comandos, logs de auditoria e memória de longo prazo.")
    }

    Rel(github, api, "Envia webhook", "HTTPS")
    Rel(api, db, "Persiste evento rotulado (status=PENDING)")
    Rel(executor, db, "Lê/Trava eventos de execução, atualiza estado")
    Rel(executor, github, "Atualiza Issues/PR/Projects", "REST/GraphQL")
    Rel(notifications, db, "Lê eventos de notificação, atualiza status de envio")
    Rel(notifications, user, "Envia mensagem / alerta HITL", "Telegram Bot API")
```

## Módulos implantáveis como imagem Docker

Os componentes principais são entregues como imagens Docker independentes que podem ser orquestradas em um ambiente local, de CI ou em um cluster leve.

- `ai-dev-api`: serviço HTTP que expõe o endpoint de webhook, valida, classifica e persiste eventos de entrada no PostgreSQL.
- `ai-dev-executor`: serviço responsável por consumir eventos de execução do banco, orquestrar o sandbox Docker, executar os prompts / engine LLM e integrar com GitHub para criar PRs e atualizar cards/issues.
- `ai-dev-notifications`: serviço responsável por consumir eventos de notificação do banco e entregar alertas HITL via Telegram.
- `ai-dev-migrations`: imagem de utilitário para aplicar migrações de banco de dados e tarefas de manutenção de persistência.

Cada imagem inclui:
- configuração via variáveis de ambiente,
- contêiner leve baseado em Python + dependências necessárias,
- healthcheck básico,
- logging estruturado para `stdout`/`stderr`.

As imagens podem ser orquestradas com `docker-compose` ou uma plataforma de container mais leve, mantendo o event store (`PostgreSQL`) como serviço externo compartilhado.
## Mapa de Capacidade → Arquitetura

| Capacidade / Área | Vive em | Governado por |
| --- | --- | --- |
| Ingestão e persistência de webhook | `api/` + `persistence/` | AD-1 |
| Orquestração de execução orientada a eventos | `executor/` + `persistence/` | AD-2, AD-7 |
| Integração com GitHub Projects / Issue / PR | `executor/` | AD-4 |
| Notificação HITL e escalonamento | `notifications/` + `persistence/` | AD-5 |
| Execução em sandbox e validação local | `executor/` | AD-6 |
| Armazenamento e persistência de memória dos agentes | `executor/` + `persistence/` | AD-8 |
| Extensibilidade e Capacidades de Agente (MCPs, Skills, Prompts) | `executor/` | AD-9 |
| Empacotamento e entrega de deployables | `infra/` + todos os serviços | AD-10 |

## Adiado

- Esquema detalhado de campos de cards do GitHub Projects e metadados de PR.
- Fluxo exato de engenharia de prompts e orquestração de LLM.
- Ambiente de implantação além do Docker local/CI (Kubernetes, nuvem, infra).
- Seleção de imagem de build para Java/Flutter e configuração de container específica para cada runtime.

