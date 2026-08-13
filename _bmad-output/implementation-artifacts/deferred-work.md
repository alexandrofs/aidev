# Deferred Work

All previously deferred work items have been resolved.

## Resolved Items

### Deferred from: code review of 1-2-endpoint-de-recepcao-validacao-e-ingestao-de-webhooks-ai-dev-api (2026-08-11)

- [x] **Engine SQLAlchemy criado em import-time em `database.py`** — Refatorado para lazy initialization com funções `get_engine()` e `get_sessionmaker()` em [`api/src/database.py`].
- [x] **Status hardcoded `"PENDING"` na resposta de duplicata idempotente** — Atualizado para consultar o `status` e `id` reais da linha persistida na tabela `events` ao capturar `IntegrityError` em [`api/src/routes/webhooks.py`].
- [x] **`db_session` sem rollback explícito entre testes** — Adicionado bloco `try...finally` executando `await session.rollback()` e `await session.close()` na fixture [`tests/api/conftest.py`].

### Deferred from: code review of 1-3-roteamento-e-consumo-idempotente-via-trava-de-banco-skip-locked (2026-08-11)

- [x] **Falta de índice composto ordenado por `created_at` para a fila de consumo (`FOR UPDATE SKIP LOCKED`)** — Criada migração Alembic [`002_add_events_consumption_index.py`](file:///Users/alexandrofs/projects/aidev/persistence/src/migrations/versions/002_add_events_consumption_index.py) criando o índice `idx_events_status_type_created` em `(status, event_type, created_at)` e adicionado teste em [`tests/persistence/test_migrations.py`].

### Deferred from: code review of 2-2-injecao-dinamica-de-contexto-mcps-skills-e-prompts (2026-08-12)

- [x] **Resolução de caminhos relativos de configuração (`PROMPTS_DIR`, `SKILLS_DIR`, `MCP_CONFIG_PATH`) baseados no CWD** — Adicionada propriedade `PROJECT_ROOT` e helper de resolução `resolve_path()` em [`executor/src/config.py`](file:///Users/alexandrofs/projects/aidev/executor/src/config.py) e atualizado o [`executor/src/context_loader.py`](file:///Users/alexandrofs/projects/aidev/executor/src/context_loader.py) para utilizar propriedades resolvidas em relação à raiz do projeto.

