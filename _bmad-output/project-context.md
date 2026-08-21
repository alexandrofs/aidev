---
project_name: 'AI Developer'
user_name: 'Alex'
date: '2026-08-20'
sections_completed:
  ['technology_stack', 'language_rules', 'framework_rules', 'testing_rules', 'quality_rules', 'workflow_rules', 'anti_patterns']
status: 'complete'
rule_count: 24
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

- **Python**: `3.12` (compatível com `>=3.9`; runtime padrão de produção e sandbox é 3.12).
- **FastAPI / Uvicorn**: `fastapi>=0.110.0`, `uvicorn[standard]>=0.28.0` (FastAPI com lifespan assíncrono e injeção de dependências).
- **PostgreSQL**: `16` (Event Store canônico; transações assíncronas com `FOR UPDATE SKIP LOCKED`).
- **SQLAlchemy & Driver**: `sqlalchemy>=2.0.0` (modo assíncrono via `AsyncSession` / `create_async_engine`), `psycopg[binary]>=3.1.0` (driver v3 nativo do PostgreSQL).
- **Pydantic**: `pydantic>=2.6.0`, `pydantic-settings>=2.2.0` (padrão Pydantic v2 com `ConfigDict` e tipagem estrita).
- **Migrações (Alembic)**: `alembic>=1.13.0` (versionamento gerenciado em `persistence/src/migrations`).
- **Docker & Engine**: `Docker Engine 24+`, Docker Compose v2, SDK `docker>=7.0.0` (orquestração de sandboxes efêmeros).
- **Testes & Qualidade**: `pytest>=8.0.0`, `pytest-asyncio>=0.23.0` (`asyncio_mode = "auto"` configurado no `pytest.ini`), `testcontainers[postgres]>=4.0.0`.
- **Cliente HTTP**: `httpx>=0.27.0` (chamadas assíncronas para APIs do GitHub REST/GraphQL e Webhooks).
- **Harness do Agente**: OpenCode runner executado dentro do container de sandbox (`SANDBOX_IMAGE=python:3.12-slim`).

---

## Critical Implementation Rules

### Language-Specific Rules (Python 3.12)

- **Assincronismo Obrigatório para I/O**: Todas as operações de banco de dados (`AsyncSession`), requisições de rede (`httpx.AsyncClient`) e workers de eventos devem ser estritamente assíncronas (`async`/`await`).
- **Pydantic v2 Idiomático**:
  - Utilizar `model_dump()`, `model_validate()` e `model_dump_json()` (nunca utilizar métodos legados do v1 como `.dict()` ou `.parse_obj()`).
  - Configuração de modelos com `model_config = ConfigDict(...)` (evitar `class Config:` legada).
  - Tipagem rigorosa com `Optional`, `Union`, `Dict`, `List` e `Annotated`.
- **SQLAlchemy 2.0 Moderno**:
  - Utilizar `select(...)`, `text(...)`, `bindparam(...)` e executar via `session.execute(...)`.
  - Proibido o uso de sintaxe legada baseada em `session.query(...)`.
- **Tratamento de Datas e Timezones**:
  - Sempre utilizar timestamps conscientes de fuso horário em UTC: `datetime.now(timezone.utc)`.
  - Não utilizar `datetime.utcnow()`, que foi marcado como depreciado no Python 3.12.
- **Tratamento de Exceções & Logs Estruturados**:
  - Utilizar exceções de domínio tipadas (ex: `executor.src.exceptions`).
  - Sempre instanciar `logger = logging.getLogger(__name__)` e incluir chaves de rastreio (`event_id`, `story_id`, `repository`).
  - Evitar captura genérica silenciosa (`except Exception:` sem log estruturado com `logger.exception(...)` ou re-raise).
- **Gerenciamento Seguro de Recursos**:
  - Utilizar context managers assíncronos (`async with`) para clientes HTTP, sessões do banco e ciclos de vida de containers.

### Framework & Architecture Rules

- **Ingestão de Webhook Atômica (AD-1 & FastAPI Gateway)**:
  - Autenticação obrigatória da assinatura HMAC-SHA256 (`X-Hub-Signature-256`) no gateway `ai-dev-api`.
  - O gateway apenas valida, classifica, resolve o repositório e persiste o evento na tabela `events` com status `PENDING` antes de responder HTTP 202 Accepted.
  - É proibido disparar execuções de agentes de forma síncrona ou em background tasks da API.
- **Consumo Concorrente e Idempotência (AD-2, AD-3 & Event Store)**:
  - Workers (`ai-dev-executor`, `ai-dev-notifications`) devem realizar o claim de eventos `PENDING` utilizando transação com `SELECT ... FOR UPDATE SKIP LOCKED` e transição imediata para `PROCESSING`.
  - Deduplicação por `event_id` único e hash SHA-256 do payload.
  - Toda transição de estado de evento deve gerar obrigatoriamente um registro correspondente na tabela `audit_logs`.
- **Exclusividade de Mutações no GitHub (AD-4)**:
  - Somente o `ai-dev-executor` possui permissão para interagir com a API do GitHub (criar branches, commits, PRs, issues e atualizar cards de Projects).
- **Sandbox Docker Efêmero e Isolamento Total (AD-6)**:
  - Toda execução do agente OpenCode, testes e compilação do repositório alvo deve rodar dentro de um container Docker descartável (`SANDBOX_IMAGE`).
  - Garantir limpeza determinística do container e diretórios temporários montados (sempre dentro de blocos `try...finally`).
- **Memória Hierárquica e Injeção de Contexto (AD-8, AD-9)**:
  - Injetar dinamicamente na sessão do sandbox: prompts estruturados (`coding.md`, `review.md`), servidores MCP e skills locais (`.agents/skills/`).
  - Persistir decisões e resumos de contexto na tabela `agent_memory` (tipos: `daily_summary`, `decision`, `long_term`) e sincronizar com `.memlog.md`.

### Testing Rules

- **Organização e Descoberta de Testes**:
  - Testes estruturados por componente: `tests/api/`, `tests/executor/`, `tests/persistence/`, `tests/unit/`.
  - Padrão estrito de nomenclatura: arquivos `test_*.py` e funções assíncronas/síncronas `test_*()`.
- **Execução Assíncrona via `pytest-asyncio`**:
  - O projeto utiliza `asyncio_mode = "auto"` configurado no `pytest.ini`.
  - Escrever testes assíncronos diretamente com `async def test_*(...)` sem necessidade de decorar explicitamente com `@pytest.mark.asyncio`.
- **Testes de Integração com Banco Real (`Testcontainers`)**:
  - Testes da camada de persistência (`tests/persistence/`) que validam concorrência (`SKIP LOCKED`), migrações Alembic e constraints relacionais devem utilizar `testcontainers[postgres]`.
- **Mocks Assíncronos e Isolamento de Serviços Externos**:
  - Chamadas de rede e APIs externas (GitHub, Telegram) devem ser mockadas utilizando `unittest.mock.AsyncMock` ou `respx`.
  - Nunca disparar chamadas HTTP externas reais durante os testes automatizados.
- **Critério de Aceite e Regressão Zero**:
  - Toda nova funcionalidade ou correção deve incluir testes correspondentes.
  - 100% dos testes devem passar ao executar `.venv/bin/pytest` antes de finalizar qualquer história.

### Code Quality & Style Rules

- **Separação Rígida de Responsabilidades**:
  - `api/src/`: Apenas endpoints HTTP, roteamento, validação de segurança HMAC e persistência inicial. Proibido acoplar lógica de sandbox ou mutações no GitHub aqui.
  - `executor/src/`: Orquestração de workers, ciclo de vida do sandbox Docker, injeção de MCP/prompts e clientes de integração com GitHub.
  - `persistence/src/`: Modelos Pydantic (`EventRecord`), `EventRepository`, utilitários de hash e scripts de migração Alembic.
- **Convenções de Nomenclatura**:
  - Funções, variáveis e métodos em `snake_case`.
  - Classes, modelos Pydantic e exceções em `PascalCase`.
  - Constantes globais em `UPPER_SNAKE_CASE`.
  - Colunas e tabelas do banco em `snake_case` com timestamps `created_at` e `updated_at`.

### Development Workflow & Critical Don't-Miss Rules

- **Workflow Autônomo com Validação Local Prévia (AD-6, AD-7)**:
  - Fases sequenciais orquestradas pelo manifesto `.aidev.yaml` (ex: `coding` e `review`).
  - É expressamente proibido abrir Pull Request no GitHub sem antes compilar o código e validar 100% dos testes/linters passando dentro do sandbox Docker efêmero.
  - Limite de até 3 tentativas de autocorreção em caso de falha de CI/testes antes de transicionar o evento para `NEEDS_HUMAN_ACTION`.
- **Anti-Patterns Críticos**:
  - ❌ Nunca utilizar `time.sleep()` síncrono em fluxos assíncronos (usar sempre `asyncio.sleep()`).
  - ❌ Nunca vazar tokens ou credenciais (`GITHUB_TOKEN`, `OPENCODE_API_KEY`, `POSTGRES_PASSWORD`) em logs estruturados ou no campo `error_log` do banco.
  - ❌ Nunca comitar alterações diretamente nas branches principais (`main`/`master`); todo código gerado deve ser submetido via branches de funcionalidade e PR.
  - ❌ Nunca ignorar erros de banco de dados sem realizar rollback explícito da `AsyncSession`.

---

## Usage Guidelines

**For AI Agents:**

- Leia este arquivo antes de iniciar o planejamento ou implementação de qualquer funcionalidade ou correção.
- Siga rigorosamente TODAS as regras e invariantes documentadas.
- Em caso de ambiguidade, priorize sempre a opção mais restritiva e segura.
- Atualize este arquivo sempre que novos padrões ou dependências estruturais forem consolidados.

**For Humans:**

- Mantenha este documento conciso e focado nas necessidades de contexto dos agentes de IA.
- Atualize quando houver mudanças arquiteturais ou alterações na stack tecnológica.
- Revise periodicamente para podar regras que se tornaram óbvias ou obsoletas.

Last Updated: 2026-08-20
