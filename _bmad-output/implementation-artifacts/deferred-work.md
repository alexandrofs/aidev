# Deferred Work

## Deferred from: code review of 1-2-endpoint-de-recepcao-validacao-e-ingestao-de-webhooks-ai-dev-api (2026-08-11)

- **Engine SQLAlchemy criado em import-time em `database.py`** — O engine singleton é criado no carregamento do módulo, antes de qualquer override de configuração de teste. Pré-existente por design (mitigado pelo override de `get_async_session`), mas pode causar problemas se o engine for referenciado diretamente fora do sistema de DI do FastAPI. Considerar lazy initialization em iteração futura. [`api/src/database.py`]

- **Status hardcoded `"PENDING"` na resposta de duplicata idempotente** — O código retorna `"status": "PENDING"` hardcoded sem consultar o estado real do evento no banco. Pode retornar informação incorreta se o evento já foi processado por um worker. Comportamento dentro do escopo do AC-5, mas melhoria desejável: consultar o status atual antes de responder. [`api/src/routes/webhooks.py`]

- **`db_session` sem rollback explícito entre testes** — Fixtures de teste não fazem rollback entre casos, potencial vazamento de estado em suítes expandidas. Atualmente mitigado pelo scope `function` que garante DB novo por teste, mas se o scope for alterado para `session` futuramente, pode causar flakiness. [`tests/api/conftest.py`]
