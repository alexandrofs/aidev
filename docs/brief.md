Here is the complete summary of the proposed architecture for your autonomous programming agent.

---

## 1. Contexto

O objetivo é construir um **agente autônomo de programação orientado a especificações (Spec-Driven Development - SDD)** que atue como um membro da equipe de desenvolvimento.

Em vez de reinventar o ciclo de vida de desenvolvimento do zero, a solução adota uma abordagem pragmática baseada na integração de ferramentas especializadas:

* **Planejamento & SDD:** Método **BMAD** para gerar artefatos estruturados em Markdown (`PRD.md`, `architecture.md`, histórias de usuário).
* **Execução Técnica:** **OpenCode** (ou Aider/Claude Code) rodando em containers isolados para alteração de código e execução de testes.
* **Orquestração & Gestão:** **GitHub Projects v2** (Kanban), **GitHub Actions** (CI/CD) e **Webhooks** como motor reativo (Event-Driven).

---

## 2. Lista de Funcionalidades

### 📋 Gestão de Especificação & Kanban

* **Parse de SDD (BMAD):** Leitura automática dos arquivos de especificação em Markdown e conversão em *Issues* do GitHub.
* **Sincronização de Status:** Movimentação automatizada dos cards no GitHub Projects v2 via API GraphQL / CLI (`gh`).

### 🛠️ Execução Autônoma de Código

* **Gatilho Reativo:** O agente acorda assim que um card é movido para a coluna `"Ready for AI"`.
* **Execução Isolada (Sandbox):** Criação de ambiente efémero em Docker com checkout da branch do projeto.
* **Edição & Validação Local:** Alteração do código, execução da suíte de testes locais e abertura automática de Pull Request (PR) com mensagens semânticas.

### 🩹 CI/CD Auto-Healing (Loop de Correção)

* **Captura de Falha de Build:** Escuta de webhooks `workflow_run` em caso de quebra no GitHub Actions.
* **Extração Cirúrgica de Logs:** Coleta de logs específicos de erro via `gh run view --log-failed` para não estourar contexto de LLM.
* **Correção Automática:** Acionamento do OpenCode em modo de correção no PR existente, com limite estrito de tentativas (*Max Retries* = 2 ou 3) para evitar loops infinitos.

### 🙋‍♂️ Human-in-the-Loop (HITL) & Alertas

* **Gestão de Ambiguidade:** Se a *spec* estiver incompleta ou faltar uma credencial, o agente pausa a tarefa, faz uma pergunta na Issue e move o card para `"Needs Human Action"`.
* **Alertas do Time:** Envio de notificações via Slack/Discord/Telegram para revisão de PRs ou solicitação de intervenção humana.

---

## 3. Resumo da Arquitetura Proposta

A arquitetura é **Híbrida e Orientada a Eventos (Event-Driven)**, eliminando requisições desnecessárias por *polling* e mantendo acoplamento fraco entre os componentes.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            GITHUB ECOSYSTEM                                 │
│  ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐   │
│  │ GitHub Projects  │      │ GitHub Issues    │      │ GitHub Actions   │   │
│  │ (Kanban Board)   │      │ & Pull Requests  │      │ (CI/CD Pipelines)│   │
│  └────────┬─────────┘      └────────▲─────────┘      └────────┬─────────┘   │
└───────────┼─────────────────────────┼─────────────────────────┼─────────────┘
            │ Webhook                 │ Git Push / PR           │ Webhook
            │ (Card moved)            │                         │ (Workflow fail)
            ▼                         │                         ▼
┌─────────────────────────────────────┴───────────────────────────────────────┐
│                      ORQUESTRADOR (FastAPI / Python)                         │
│  - Event Router & Webhook Handler                                           │
│  - State & Retry Control (Max 3 retries)                                    │
│  - GitHub GraphQL/REST API Client                                           │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      SANDBOX DOCKER (Execução Efémera)                      │
│  - OpenCode Engine                                                          │
│  - Execução de Testes / Linters / Build                                     │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       SISTEMA DE NOTIFICAÇÃO (HITL)                         │
│  - Webhooks para Slack / Discord / Telegram                                 │
└─────────────────────────────────────────────────────────────────────────────┘

```

### Componentes Chave do Fluxo:

1. **Ingress / Router de Eventos (Orquestrador em Python/FastAPI):**
* Serviço leve que escuta Webhooks do GitHub.
* Filtra eventos relevantes (`projects_v2_item`, `workflow_run`) e gerencia os retries.


2. **Camada de Automação de Projetos (GitHub Projects API):**
* Abstração GraphQL para manipular o campo `Status` dos itens no painel Kanban.


3. **Mecanismo de Execução (OpenCode + Docker):**
* Container subido sob demanda para cada tarefa. Garante que dependências e código sejam executados sem contaminar o servidor hospedeiro.


4. **Motor de Notificação (Notificações HITL):**
* Canal direto de comunicação com os desenvolvedores para aprovação de PRs e resolução de bloqueios.