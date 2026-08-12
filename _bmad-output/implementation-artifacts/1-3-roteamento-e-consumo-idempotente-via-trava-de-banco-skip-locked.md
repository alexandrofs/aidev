---
baseline_commit: 0203a84e59e9ab258c52ee9b1de8623bfb2796f3
---

# Story 1.3: Roteamento e Consumo Idempotente via Trava de Banco (`SKIP LOCKED`)

Status: review

## Story

As a worker do AIDEV (`ai-dev-executor` ou `ai-dev-notifications`),
I want consumir eventos em status `PENDING` diretamente do PostgreSQL filtrando por tipo de evento e aplicando trava de registro (`FOR UPDATE SKIP LOCKED`),
so that eventos concorrentes ou duplicados sejam processados exatamente uma vez com garantia de idempotência e sem necessidade de um broker intermediário.

## Acceptance Criteria

1. **Seleção e Trava Atômica de Eventos Elegíveis (`FOR UPDATE SKIP LOCKED`) (AC: 1)**
   - **Given** múltiplos eventos gravados na tabela `events` com status `PENDING`
   - **When** um worker (`ai-dev-executor` ou `ai-dev-notifications`) consultar novos eventos para processamento filtrando por `event_type` (ou lista de tipos de evento)
   - **Then** a consulta SQL deve utilizar a trava `FOR UPDATE SKIP LOCKED` para selecionar a linha e alterar atomicamente o status para `'PROCESSING'` e `updated_at = NOW()`
   - **And** a operação deve garantir que nenhum outro worker concorrente consiga selecionar ou travar a mesma linha simultaneamente.

2. **Garantia de Idempotência e Tratamento de Reprocessamento (AC: 2)**
   - **Given** um evento recebido para consumo que já foi anteriormente processado (`COMPLETED`) ou está em processamento (`PROCESSING`) com o mesmo `event_id` ou com hash de payload idêntico
   - **When** a rotina de consumo ou roteamento verificar a elegibilidade do evento
   - **Then** o sistema deve detectar a duplicata idempotente sem reexecutar os efeitos colaterais (mutações no GitHub ou notificações)
   - **And** atualizar/marcar a tentativa como ignorada ou resolvida de forma idempotente no banco de dados.

3. **Transições de Estado do Evento e Trilha de Auditoria (AC: 3)**
   - **Given** um evento em estado `'PROCESSING'`
   - **When** o processamento pelo worker for concluído com sucesso ou falhar
   - **Then** o status do evento deve ser atualizado para `'COMPLETED'` ou `'FAILED'` (incrementando `retry_count` se for falha recuperável)
   - **And** um registro correspondente de auditoria deve ser inserido na tabela `audit_logs` contendo `event_id`, `action` (`CLAIMED`, `COMPLETED`, `FAILED`, `RETRY`), `actor` (identificador do worker) e `details` (JSONB).

4. **Abstração de Repositório de Eventos no Módulo `persistence` (AC: 4)**
   - **Given** o módulo de persistência do projeto (`persistence/src`)
   - **When** a história for implementada
   - **Then** deve ser criada uma classe de repositório assíncrono (ex: `EventRepository` em `persistence/src/events.py` ou `persistence/src/repository.py`) encapsulando as operações de `claim_event`, `complete_event`, `fail_event`, `calculate_payload_hash` e `audit_log`
   - **And** a abstração deve suportar PostgreSQL 16 com `FOR UPDATE SKIP LOCKED` e manter compatibilidade com SQLite para a suíte de testes unitários locais.

5. **Suíte de Testes Automatizados de Concorrência e Idempotência (AC: 5)**
   - **Given** a classe `EventRepository` e uma base de dados de teste (PostgreSQL local / Docker)
   - **When** a suíte de testes `pytest` for executada em `tests/persistence/test_event_consumption.py`
   - **Then** os testes automatizados devem validar:
     - Trava de concorrência com múltiplos workers concorrentes (garantindo que 2 workers paralelos nunca consumam o mesmo evento `PENDING`)
     - Mudança atômica de status `PENDING` -> `PROCESSING` -> `COMPLETED` / `FAILED`
     - Detecção de idempotência por `event_id` e por hash de payload (`SHA-256`)
     - Gravação de logs de auditoria na tabela `audit_logs`.

## Tasks / Subtasks

- [x] Task 1: Abstração do Repositório de Eventos (`EventRepository`) em `persistence/src/` (AC: 1, 3, 4)
  - [x] Criar arquivo `persistence/src/repository.py` com a classe `EventRepository` aceitando `AsyncSession` do SQLAlchemy
  - [x] Implementar método `claim_event(event_types: list[str], worker_id: str) -> Optional[EventRecord]` executando `SELECT ... FOR UPDATE SKIP LOCKED` e `UPDATE events SET status = 'PROCESSING', updated_at = NOW()` atomicamente
  - [x] Implementar tratamento para que em dialectos de banco sem suporte nativo a `SKIP LOCKED` (ex: SQLite em testes unitários simples) a consulta execute um fallback gracioso de lock sem estourar exceção de sintaxe
  - [x] Implementar métodos `complete_event(event_id: str, worker_id: str, details: dict = None)` e `fail_event(event_id: str, worker_id: str, error_message: str, max_retries: int = 3)`

- [x] Task 2: Mecanismo de Idempotência por Hash de Payload e Audit Log (AC: 2, 3)
  - [x] Adicionar função utilitária `compute_payload_hash(payload: dict) -> str` que calcula o hash SHA-256 canônico do payload JSON
  - [x] Implementar método `check_idempotency(event_id: str, payload_hash: str) -> bool` no repositório para verificar se um evento idêntico já foi processado com sucesso (`COMPLETED`)
  - [x] Implementar método `add_audit_log(event_id: str, action: str, actor: str, details: dict = None)` que insere registros na tabela `audit_logs`

- [x] Task 3: Exportar repositório e modelos na interface do pacote `persistence` (AC: 4)
  - [x] Atualizar `persistence/src/__init__.py` exportando `EventRepository`, `DatabaseSettings` e modelos/dtos de evento
  - [x] Garantir tipagem limpa com Pydantic v2 e dataclasses/SQLAlchemy models para facilitar consumo por `ai-dev-executor` e `ai-dev-notifications`

- [x] Task 4: Suíte de Testes Automatizados de Concorrência e Idempotência (AC: 5)
  - [x] Criar `tests/persistence/test_event_consumption.py`
  - [x] Testar consumo concorrente usando `asyncio.gather` para simular 5+ workers tentando consumir simultaneamente 5 eventos `PENDING` do PostgreSQL, verificando distribuição 1:1 sem duplicação
  - [x] Testar ciclo de vida completo: `claim_event` -> `complete_event` e `claim_event` -> `fail_event` (com verificação de incrementação de `retry_count`)
  - [x] Testar verificação de idempotência por payload hash e `event_id`
  - [x] Testar criação dos registros de auditoria em `audit_logs`

- [x] Task 5: Documentação no `README.md` (AC: 4)
  - [x] Atualizar o `README.md` da raiz descrevendo o mecanismo de consumo via `SKIP LOCKED` (AD-2), a classe `EventRepository` e as instruções para rodar os testes de concorrência

## Dev Notes

### Contexto de Arquitetura & Guardrails

- **AD-2 (Consumo via PostgreSQL com SKIP LOCKED):** Os trabalhadores `ai-dev-executor` e `ai-dev-notifications` consultam a tabela `events` diretamente no banco sem broker intermediário. A query de claim MUST utilizar `FOR UPDATE SKIP LOCKED` para evitar contenção e garroteamento entre workers paralelas.
- **Índice Existente de Apoio:** Na História 1.1 foi criado o índice composto `idx_events_status_type` em `(status, event_type)`. A query do repositório deve obrigatoriamente se beneficiar desse índice filtrando por `WHERE status = 'PENDING' AND event_type IN (...)`.
- **AD-3 (Controle de Idempotência):** Garantir idempotência no consumo via `event_id` ou hash SHA-256 do payload.
- **AD-5 (Notificações & Audit Trail):** Transições de estado (`CLAIMED`, `COMPLETED`, `FAILED`) devem gravar entradas na tabela `audit_logs` (NFR2 Auditabilidade).
- **AD-8 (Memória Hierárquica):** Mudar status do evento no PostgreSQL garante o Nível 2 da memória hierárquica do sistema.

### Exemplo de Query Atômica com `FOR UPDATE SKIP LOCKED` em SQLAlchemy (Async)

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any
import hashlib
import json

class EventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def claim_event(
        self, 
        event_types: List[str], 
        worker_id: str,
        skip_locked: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Seleciona e trava atomicamente um evento em PENDING filtrando pelos tipos desejados.
        Muda o status para 'PROCESSING'.
        """
        lock_clause = "FOR UPDATE SKIP LOCKED" if skip_locked else "FOR UPDATE"
        
        # Em PostgreSQL, CTE com UPDATE garante atomicidade em uma única instrução SQL:
        query = text(f"""
            WITH eligible AS (
                SELECT id 
                FROM events 
                WHERE status = 'PENDING' 
                  AND event_type = ANY(:event_types)
                ORDER BY created_at ASC
                LIMIT 1
                {lock_clause}
            )
            UPDATE events
            SET status = 'PROCESSING',
                updated_at = NOW()
            FROM eligible
            WHERE events.id = eligible.id
            RETURNING events.id, events.event_id, events.event_type, events.status, events.payload, events.retry_count;
        """)

        result = await self.session.execute(query, {"event_types": event_types})
        row = result.fetchone()
        if not row:
            return None
            
        event_dict = {
            "id": str(row.id),
            "event_id": row.event_id,
            "event_type": row.event_type,
            "status": row.status,
            "payload": row.payload if isinstance(row.payload, dict) else json.loads(row.payload),
            "retry_count": row.retry_count
        }

        # Registrar log de auditoria da trava
        await self.add_audit_log(
            event_id=row.event_id,
            action="CLAIMED",
            actor=worker_id,
            details={"event_type": row.event_type}
        )
        await self.session.commit()
        return event_dict
```

### Cálculo Canônico de Hash de Payload (`SHA-256`)

```python
def compute_payload_hash(payload: dict) -> str:
    """Retorna hash SHA-256 determinístico de um dicionário JSON."""
    canonical_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()
```

### Estrutura de Arquivos Modificada / Criada

```text
{project-root}/
  README.md                             # Atualizado com documentação do EventRepository e SKIP LOCKED
  pytest.ini                            # Configuração de pythonpath para suíte de testes
  persistence/
    src/
      __init__.py                       # Exportação do EventRepository, EventRecord e compute_payload_hash
      repository.py                     # Implementação da classe EventRepository e atomic lock SKIP LOCKED
  tests/
    persistence/
      test_event_consumption.py        # Suíte de testes de concorrência, idempotência e audit log
```

### Previous Story Intelligence

- **História 1.1 (`ai-dev-migrations`):**
  - Tabela `events` contém as colunas `id` (UUID), `event_id` (VARCHAR UNIQUE), `event_type` (VARCHAR), `status` (VARCHAR, default `'PENDING'`), `payload` (JSONB), `retry_count` (INTEGER), `created_at`, `updated_at`.
  - Índice composto `idx_events_status_type` existe em `(status, event_type)`.
  - Tabela `audit_logs` contém `id`, `event_id`, `action`, `actor`, `details` (JSONB), `created_at`.
  - Driver de banco configurado é `postgresql+psycopg://` em `DatabaseSettings` (`persistence/src/config.py`).
- **História 1.2 (`ai-dev-api`):**
  - Eventos de webhook são ingeridos com `status = 'PENDING'` e `event_id = X-GitHub-Delivery`.
  - Em testes automatizados, SQLAlchemy em modo assíncrono com `psycopg3` lida com instâncias de `AsyncSession`.

### References

- [ARCHITECTURE-SPINE.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/architecture/architecture-AI%20Developer-2026-08-09/ARCHITECTURE-SPINE.md#L38-L87) - Decisões de Arquitetura AD-1, AD-2, AD-3, AD-5, AD-8
- [epics.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/epics.md#L128-L140) - Requisitos e Critérios de Aceite da Story 1.3
- [1-1-schema-do-event-store-e-migracoes-em-postgresql-ai-dev-migrations.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/implementation-artifacts/1-1-schema-do-event-store-e-migracoes-em-postgresql-ai-dev-migrations.md) - Esquema de migrações e índices
- [1-2-endpoint-de-recepcao-validacao-e-ingestao-de-webhooks-ai-dev-api.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/implementation-artifacts/1-2-endpoint-de-recepcao-validacao-e-ingestao-de-webhooks-ai-dev-api.md) - Padrões de inserção e sessão async

## Dev Agent Record

### Agent Model Used

Gemini 3.6 Flash (High)

### Debug Log References

### Completion Notes List

- Created story context file for 1.3 Routing and Idempotent Consumption via DB Lock (`SKIP LOCKED`).
- Implemented `EventRepository` in `persistence/src/repository.py` with atomic claim support via `FOR UPDATE SKIP LOCKED` (PostgreSQL CTE) and atomic subquery fallback (SQLite).
- Implemented state transition methods: `claim_event`, `complete_event`, `fail_event` (with retry limit and state transition to FAILED/RETRY), and `add_audit_log`.
- Implemented canonical SHA-256 payload hashing (`compute_payload_hash`) and idempotency checks (`check_idempotency`).
- Exported `EventRepository`, `EventRecord`, `compute_payload_hash` in `persistence/src/__init__.py`.
- Created automated test suite `tests/persistence/test_event_consumption.py` covering unit cases and multi-worker concurrent claim testing using `asyncio.gather` for both SQLite and PostgreSQL.
- Updated root `README.md` with detailed usage documentation and test execution commands.
- Verified 50 total project tests passing cleanly without regressions.

### File List

- `_bmad-output/implementation-artifacts/1-3-roteamento-e-consumo-idempotente-via-trava-de-banco-skip-locked.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `persistence/src/__init__.py`
- `persistence/src/repository.py`
- `tests/persistence/test_event_consumption.py`
- `pytest.ini`
- `README.md`

### Change Log

- Story 1.3 specification created (Date: 2026-08-12)
- Story 1.3 implementation completed and verified with 50 passing unit/integration tests (Date: 2026-08-12)

