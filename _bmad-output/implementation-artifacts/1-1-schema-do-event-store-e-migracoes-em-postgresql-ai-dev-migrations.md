---
baseline_commit: 2ad61006e0e260093994dc994e44dfc295ae973e
---

# Story 1.1: Schema do Event Store e Migrações em PostgreSQL (`ai-dev-migrations`)

Status: review

## Story

As a desenvolvedor do AIDEV,
I want um esquema de banco de dados PostgreSQL com tabelas de eventos, status, payloads e histórico de auditoria empacotados em um utilitário de migração (`ai-dev-migrations`), acompanhado de ambiente Docker Compose para testes locais, testes automatizados e documentação inicial (`README.md`),
so that o sistema possa registrar o estado dos eventos de forma persistente, estruturada e versionada, e a equipe possa subir a infraestrutura e validar o ambiente facilmente.

## Acceptance Criteria

1. **Criação Inicial do Banco de Dados e Esquema de Migração (AC: 1)**
   - **Given** um banco de dados PostgreSQL zerado ou desatualizado
   - **When** a imagem de migração `ai-dev-migrations` for executada
   - **Then** as tabelas `events`, `agent_memory` e `audit_logs` devem ser criadas com os esquemas e tipos de dados corretos.

2. **Esquema da Tabela `events` e Status Padrão (AC: 2, 3)**
   - **Given** a tabela `events` criada no PostgreSQL
   - **Then** ela deve conter exatamente os campos: `id` (UUID PK), `event_id` (VARCHAR UNIQUE), `event_type` (VARCHAR), `status` (VARCHAR, default `'PENDING'`), `payload` (JSONB), `retry_count` (INTEGER, default 0), `created_at` (TIMESTAMPTZ, default `NOW()`), `updated_at` (TIMESTAMPTZ, default `NOW()`).

3. **Criação de Índices Otimizados para Concorrência e Idempotência (AC: 4)**
   - **Given** a execução da migração no PostgreSQL
   - **Then** os seguintes índices devem ser criados:
     - `idx_events_status_type`: índice composto em `(status, event_type)` para otimizar as consultas `FOR UPDATE SKIP LOCKED` executadas pelos workers (`ai-dev-executor` e `ai-dev-notifications`)
     - `idx_events_event_id`: índice `UNIQUE` na coluna `event_id` para garantir a idempotência de gravação de webhooks do GitHub (AD-3).

4. **Esquema da Tabela `agent_memory` e `audit_logs` (AC: 5)**
   - **Given** os requisitos de memória hierárquica (AD-8) e auditabilidade (NFR2)
   - **Then** a tabela `agent_memory` deve conter `id` (UUID PK), `story_id` (VARCHAR), `memory_type` (VARCHAR: `daily_summary`, `decision`, `long_term`), `content` (JSONB/TEXT), `created_at` (TIMESTAMPTZ), `updated_at` (TIMESTAMPTZ) com índice em `(story_id, memory_type)`
   - **And** a tabela `audit_logs` deve conter `id` (UUID PK), `event_id` (VARCHAR), `action` (VARCHAR), `actor` (VARCHAR), `details` (JSONB), `created_at` (TIMESTAMPTZ) com índice em `(event_id)`.

5. **Empacotamento Docker da Imagem de Migração (`ai-dev-migrations`) (AC: 6)**
   - **Given** o utilitário de migração baseado em Python / Alembic
   - **When** o comando `docker build` for executado na pasta do componente
   - **Then** deve ser gerada uma imagem OCI/Docker imutável `ai-dev-migrations` que executa a migração no startup e encerra com exit code 0 em caso de sucesso ou exit code 1 em falha, conectando via variáveis de ambiente (`DATABASE_URL` ou `POSTGRES_*`).

6. **Orquestração Local via Docker Compose (AC: 7)**
   - **Given** um ambiente local de desenvolvimento com Docker
   - **When** o comando `docker compose up` for executado na raiz do projeto
   - **Then** um container PostgreSQL 16 (`postgres`) e o container de migrações (`ai-dev-migrations`) devem ser iniciados, com o container de migrações aguardando a prontidão do banco (healthcheck) antes de aplicar as migrações e finalizar com sucesso (exit code 0).

7. **Suíte de Testes Automatizados de Migração (AC: 8)**
   - **Given** o código da camada de persistência e os scripts de migração
   - **When** o comando de testes (ex: `pytest`) for executado
   - **Then** os testes automatizados devem verificar programmaticamente a aplicação correta das migrações (schema upgrade), a criação dos índices (`idx_events_status_type` e `idx_events_event_id`), a aplicação do status padrão `'PENDING'` e a garantia da constraint de unicidade no `event_id`.

8. **Documentação Principal do Projeto (`README.md`) (AC: 9)**
   - **Given** o repositório do projeto AI Developer
   - **When** um desenvolvedor acessar a raiz do repositório
   - **Then** deve haver um arquivo `README.md` detalhando a visão geral da arquitetura do projeto, os componentes principais (`ai-dev-api`, `ai-dev-executor`, `ai-dev-notifications`, `ai-dev-migrations`), as instruções para subir a infraestrutura com Docker Compose e como executar os testes automatizados.

## Tasks / Subtasks

- [x] Task 1: Estrutura inicial do módulo de persistência e suporte a migrações (AC: 1, 6)
  - [x] Criar diretório `persistence/` com módulo Python para migrações
  - [x] Configurar Alembic com suporte assíncrono/síncrono SQLAlchemy em PostgreSQL 16
  - [x] Criar gerenciador de configuração leitor de variáveis de ambiente (`DATABASE_URL`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`)

- [x] Task 2: Implementar scripts de migração Alembic para `events`, `agent_memory` e `audit_logs` (AC: 2, 3, 4, 5)
  - [x] Criar migração inicial Alembic para a tabela `events` com valor padrão `'PENDING'` em status
  - [x] Adicionar constraints e índices: `idx_events_status_type` e `idx_events_event_id` (UNIQUE)
  - [x] Criar migração para tabela `agent_memory` com índice `idx_agent_memory_story_type`
  - [x] Criar migração para tabela `audit_logs` com índice `idx_audit_logs_event_id`

- [x] Task 3: Dockerfile e Script de Entrypoint de Migração (`ai-dev-migrations`) (AC: 6)
  - [x] Criar `persistence/Dockerfile` ou `infra/docker/migrations.Dockerfile` para a imagem `ai-dev-migrations`
  - [x] Adicionar script `entrypoint.sh` / runner Python com lógica de wait-for-postgres / retry para aguardar o banco estar pronto antes de executar `alembic upgrade head`
  - [x] Garantir saída limpa com exit code 0/1 e logs estruturados em stdout

- [x] Task 4: Criar arquivo `docker-compose.yml` para subida do ambiente local (AC: 7)
  - [x] Criar `docker-compose.yml` na raiz do projeto contendo o serviço PostgreSQL 16 com healthcheck
  - [x] Configurar o serviço `ai-dev-migrations` para compilar o Dockerfile de `persistence/` e aguardar a condição `service_healthy` do `postgres`
  - [x] Garantir mapeamento de volumes de persistência de dados do PostgreSQL para desenvolvimento local

- [x] Task 5: Suíte de Testes Automatizados da Infraestrutura e Migrações (AC: 8)
  - [x] Criar estrutura de testes em `tests/persistence/` ou `persistence/tests/` utilizando `pytest` + `sqlalchemy` / `psycopg`
  - [x] Implementar testes automatizados para verificar a aplicação das migrações, a existência dos índices otimizados e a integridade das constraints (`UNIQUE event_id`, default `'PENDING'`)

- [x] Task 6: Criar o arquivo `README.md` na raiz do projeto (AC: 9)
  - [x] Escrever o `README.md` com visão geral do AI Developer, arquitetura orientada a eventos e descrição do Event Store PostgreSQL
  - [x] Documentar comandos para inicializar a infraestrutura (`docker compose up`), rodar migrações manuais e executar a suíte de testes automatizados

## Dev Notes

### Contexto de Arquitetura & Guardrails

- **AD-1 (Persistência de Webhook):** A tabela `events` é a primeira parada de todo webhook recebido pela `ai-dev-api`. Ela deve aceitar inserção atômica com status `PENDING` e payload `JSONB`.
- **AD-2 (Consumo via PostgreSQL com SKIP LOCKED):** Os trabalhadores `ai-dev-executor` e `ai-dev-notifications` consultarão a tabela `events` usando a query `SELECT ... WHERE status = 'PENDING' AND event_type = :type FOR UPDATE SKIP LOCKED`. Por isso, o índice composto `idx_events_status_type` em `(status, event_type)` é CRÍTICO para a performance do locking de linha no PostgreSQL 16.
- **AD-3 (Idempotência):** O campo `event_id` possui restrição `UNIQUE` (`idx_events_event_id`) para evitar reinserção duplicada de webhooks idênticos do GitHub.
- **AD-8 (Memória Hierárquica):** A tabela `agent_memory` atende aos Níveis 2 e 3 da memória dos agentes (histórico de execuções no PostgreSQL e resumos diários sincronizados).
- **AD-10 (Empacotamento OCI/Docker):** O componente `ai-dev-migrations` é entregue como uma imagem Docker auto-contida.

### Estrutura de Arquivos Recomendada

```text
{project-root}/
  README.md                     # Documentação principal do repositório
  docker-compose.yml            # Ambientes local para subida do PG + ai-dev-migrations
  persistence/
    Dockerfile                  # Imagem OCI para ai-dev-migrations
    alembic.ini                 # Configuração do Alembic
    entrypoint.sh               # Script de espera pelo PG e execução de migrations
    pyproject.toml              # Dependências do pacote de persistência (alembic, psycopg, pydantic-settings, pytest)
    src/
      config.py                 # Leitura de variáveis de ambiente para conexão DB
      migrations/
        env.py                  # Script de execução do Alembic
        script.py.mako          # Template para novas revisões
        versions/               # Arquivos de migração (.py)
          001_initial_schema.py # Migração das tabelas events, agent_memory, audit_logs
  tests/
    persistence/
      test_migrations.py        # Testes automatizados da camada de persistência
```

### Exemplo de `docker-compose.yml`

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    container_name: aidev-postgres
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-aidev}
      POSTGRES_USER: ${POSTGRES_USER:-aidev}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-aidev}
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-aidev} -d ${POSTGRES_DB:-aidev}"]
      interval: 5s
      timeout: 5s
      retries: 5
    volumes:
      - postgres_data:/var/lib/postgresql/data

  ai-dev-migrations:
    build:
      context: ./persistence
      dockerfile: Dockerfile
    container_name: aidev-migrations
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_PORT: 5432
      POSTGRES_DB: ${POSTGRES_DB:-aidev}
      POSTGRES_USER: ${POSTGRES_USER:-aidev}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-aidev}
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  postgres_data:
```

### Variáveis de Ambiente Suportadas

- `DATABASE_URL` (opcional, ex: `postgresql://user:pass@localhost:5432/aidev`)
- `POSTGRES_HOST` (default: `localhost`)
- `POSTGRES_PORT` (default: `5432`)
- `POSTGRES_DB` (default: `aidev`)
- `POSTGRES_USER` (default: `aidev`)
- `POSTGRES_PASSWORD` (default: `aidev`)
- `MAX_RETRIES` (default: `30` tentativas de espera no entrypoint)

### References

- [ARCHITECTURE-SPINE.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/architecture/architecture-AI%20Developer-2026-08-09/ARCHITECTURE-SPINE.md#L38-L87) - Decisões de Arquitetura AD-1, AD-2, AD-3, AD-8 e AD-10
- [epics.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/epics.md#L102-L114) - Requisitos e Critérios de Aceite da Story 1.1

## Dev Agent Record

### Agent Model Used

Gemini 3.6 Flash (High)

### Debug Log References

- Offline DDL test verified: `alembic upgrade head --sql` produces exact DDL for `events`, `agent_memory`, `audit_logs` and all required indexes.

### Completion Notes List

- ✅ Implemented Alembic environment and configuration module in `persistence/` reading database settings via Pydantic (`DatabaseSettings`).
- ✅ Created initial migration `001_initial_schema.py` covering tables `events`, `agent_memory`, and `audit_logs` with all indexes (`idx_events_status_type`, `idx_events_event_id`, `idx_agent_memory_story_type`, `idx_audit_logs_event_id`) and defaults (`status = 'PENDING'`, `retry_count = 0`).
- ✅ Built OCI-compliant `Dockerfile` and robust `entrypoint.sh` wait-for-postgres retry runner for `ai-dev-migrations`.
- ✅ Created root `docker-compose.yml` for PostgreSQL 16 + `ai-dev-migrations` local orchestration with healthchecks.
- ✅ Authored automated test suite (`tests/persistence/test_migrations.py` and `tests/persistence/test_offline_migrations.py`) covering offline DDL generation and live PostgreSQL migrations.
- ✅ Documented architecture overview, database schema details, local Docker Compose setup, manual migration execution, and automated testing instructions in `README.md`.

### File List

- `README.md`
- `docker-compose.yml`
- `persistence/pyproject.toml`
- `persistence/alembic.ini`
- `persistence/Dockerfile`
- `persistence/entrypoint.sh`
- `persistence/src/config.py`
- `persistence/src/migrations/env.py`
- `persistence/src/migrations/script.py.mako`
- `persistence/src/migrations/versions/001_initial_schema.py`
- `tests/persistence/test_migrations.py`
- `tests/persistence/test_offline_migrations.py`

### Change Log

- Initial implementation of PostgreSQL Event Store schema and migration utility (`ai-dev-migrations`) (Date: 2026-08-10)

