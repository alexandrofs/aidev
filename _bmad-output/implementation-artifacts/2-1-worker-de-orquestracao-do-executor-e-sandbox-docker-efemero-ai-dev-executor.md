---
baseline_commit: 5b501cb51bb4c0002167d301ebcecfef72d733b8
---
# Story 2.1: Worker de Orquestração do Executor e Sandbox Docker Efêmero (`ai-dev-executor`)

Status: done

## Story

As a sistema AIDEV,
I want um worker em Python (`ai-dev-executor`) que consuma eventos elegíveis do PostgreSQL via trava de linha (`SKIP LOCKED`) e inicialize/destrua um container Docker efêmero para cada execução,
so that qualquer alteração de código, análise ou execução de testes ocorra em um ambiente isolado, reproduzível, auditável e sem contaminação do host.

## Acceptance Criteria

1. **Instanciação e Orquestração do Container Sandbox Efêmero (AC: 1)**
   - **Given** um evento de execução (ex: `event_type = 'workflow.execution'`) reivindicado do PostgreSQL via `EventRepository.claim_event(['workflow.execution'], worker_id)`
   - **When** a rotina de orquestração do executor (`executor/src/sandbox.py`) for acionada
   - **Then** o worker deve instanciar um container Docker efêmero configurado via Docker SDK para Python (`docker`), utilizando uma imagem base isolada (ex: `python:3.12-slim` ou imagem de sandbox configurada)
   - **And** a inicialização deve montar volumes temporários efêmeros e injetar variáveis de ambiente necessárias para a sessão de execução do agente.

2. **Teardown Completo e Isolamento Rigoroso (AC: 2)**
   - **Given** o término da execução de uma história (seja por sucesso `COMPLETED`, falha `FAILED` ou interrupção graciosa)
   - **When** a sessão do sandbox for encerrada
   - **Then** o orquestrador deve executar o teardown completo do container (invocando `container.stop()` e `container.remove(v=True, force=True)`) e apagar os volumes/diretórios efêmeros criados
   - **And** garantir zero vazamento de processos suspensos, contaminação de arquivos ou resíduos de execução no host (`zero leakage`).

3. **Ciclo de Loop de Consumo e Gestão de Sinais no Worker (`ai-dev-executor`) (AC: 3)**
   - **Given** o serviço `ai-dev-executor` rodando em segundo plano
   - **When** iniciado via script principal (`executor/src/main.py`)
   - **Then** ele deve executar um loop assíncrono de polling contínuo consumindo eventos `PENDING` via `EventRepository`, aplicando `backoff` configurável durante períodos sem novos eventos
   - **And** interceptar os sinais do sistema operacional (`SIGINT`, `SIGTERM`) para realizar um encerramento gracioso (*graceful shutdown*), aguardando a finalização do job em andamento e garantindo o teardown do container ativo antes de sair.

4. **Empacotamento OCI/Docker do Serviço `ai-dev-executor` (AC: 4)**
   - **Given** o diretório `executor/` no repositório
   - **When** a história for concluída
   - **Then** a estrutura deve contar com:
     - Código-fonte modular em `executor/src/` (`main.py`, `worker.py`, `sandbox.py`, `config.py`)
     - `executor/Dockerfile` multi-stage com Python 3.12 e dependências do projeto (`docker`, `sqlalchemy`, `psycopg`, `pydantic`, `persistence`)
     - Serviço `ai-dev-executor` adicionado no `docker-compose.yml` com montagem do socket do Docker (`/var/run/docker.sock:/var/run/docker.sock`) e dependências de `postgres` e `ai-dev-migrations`.

5. **Suíte de Testes Automatizados com Mocks e Testes Integrados (AC: 5)**
   - **Given** o orquestrador `DockerSandboxManager` e o worker em `executor/src/`
   - **When** a suíte de testes em `tests/executor/` for executada via `pytest`
   - **Then** os testes devem cobrir:
     - Ciclo de criação, execução de comandos e remoção de containers com mocks do Docker SDK (`unittest.mock.MagicMock` / `patch`)
     - Garantia de teardown em bloco `finally:` quando ocorrerem exceções dentro do sandbox
     - Testes do worker loop com simulação de consumo de evento (`claim_event`), transição de status (`COMPLETED` / `FAILED`) e encerramento gracioso via sinais `SIGTERM`/`SIGINT`.

---

## Tasks / Subtasks

- [x] Task 1: Módulo de Configuração e Modelo de Orquestração do Sandbox (`executor/src/config.py` e `executor/src/sandbox.py`) (AC: 1, 2)
  - [x] Criar `executor/src/config.py` com `ExecutorSettings` usando `pydantic-settings` (Docker socket, imagem base do sandbox, timeouts, poll interval, volume mounts)
  - [x] Criar classe `DockerSandboxManager` em `executor/src/sandbox.py` encapsulando cliente `docker.from_env()`
  - [x] Implementar contexto ou método `create_sandbox(execution_id: str, env_vars: dict = None)` que cria o container com `detach=True` e monta diretórios/volumes temporários
  - [x] Implementar método `cleanup_sandbox(container_id_or_object, volume_paths: list)` em bloco `finally:` com `stop()` e `remove(v=True, force=True)`

- [x] Task 2: Worker de Loop de Consumo e Graceful Shutdown (`executor/src/worker.py` e `executor/src/main.py`) (AC: 1, 3)
  - [x] Criar `executor/src/worker.py` com a classe `ExecutorWorker` integrando `EventRepository` do pacote `persistence`
  - [x] Implementar método `run_loop()` que busca eventos `workflow.execution` com status `PENDING` via `claim_event`
  - [x] Implementar a transição atômica para `PROCESSING` -> executar job no `DockerSandboxManager` -> atualizar para `COMPLETED` ou `FAILED` (com registro em `audit_logs`)
  - [x] Criar `executor/src/main.py` configurando escuta de sinais `signal.SIGINT` e `signal.SIGTERM` para encerramento limpo (flag `running = False` e `await stop()`)

- [x] Task 3: Empacotamento Docker e Integração no Docker Compose (AC: 4)
  - [x] Criar `executor/Dockerfile` multi-stage otimizado para Python 3.12
  - [x] Atualizar `docker-compose.yml` adicionando o serviço `ai-dev-executor` com variáveis de ambiente e volume mount `/var/run/docker.sock:/var/run/docker.sock`
  - [x] Garantir dependências `depends_on: postgres: service_healthy` e `ai-dev-migrations: service_completed_successfully`

- [x] Task 4: Suíte de Testes Automatizados de Orquestração e Worker (AC: 5)
  - [x] Criar `tests/executor/test_sandbox.py` e `tests/executor/test_worker.py`
  - [x] Mockar chamadas da API do Docker SDK em `test_sandbox.py` para testar `run_sandbox` e resiliência de `cleanup_sandbox` em falhas
  - [x] Testar ciclo completo do worker em `test_worker.py` (claim, sandbox dispatch, audit log, error handling, retry policy e signal shutdown)
  - [x] Validar que 100% dos testes da suíte completa passam sem regressão.

- [x] Task 5: Documentação no `README.md` (AC: 4)
  - [x] Atualizar o `README.md` da raiz descrevendo o componente `ai-dev-executor`, a arquitetura do sandbox efêmero Docker (AD-6) e como rodar o worker e seus testes.

### Review Findings

- [x] [Review][Patch] Execução síncrona do Docker SDK bloqueia o Event Loop do AsyncIO [executor/src/worker.py:76-80]
- [x] [Review][Patch] Ausência de tratamento de timeout e exceções da API do Docker em execute_job [executor/src/sandbox.py:102-107]
- [x] [Review][Patch] Risco de OOM (Out of Memory) e estouro de payload por leitura ilimitada de logs [executor/src/sandbox.py:105-106]
- [x] [Review][Patch] Permissão do diretório efêmero temporário criada com umask padrão do SO [executor/src/sandbox.py:45]
- [x] [Review][Patch] Validação de tipo no payload do evento em _process_event [executor/src/worker.py:70-73]

---

## Dev Notes

### Contexto de Arquitetura & Guardrails

- **AD-2 (Consumo via PostgreSQL com `SKIP LOCKED`):** O worker `ai-dev-executor` consome eventos diretamente do banco PostgreSQL usando a abstração `EventRepository.claim_event(['workflow.execution'], worker_id)`.
- **AD-4 (Propriedade do Agente de Execução):** Mutações no GitHub e orquestração de workflows residem exclusivamente no `ai-dev-executor`.
- **AD-6 (Sandbox Docker Efêmero):** Toda execução deve rodar em um container isolado, montando diretório efêmero e garantindo destruição completa (`remove(v=True, force=True)`) ao final da execução.
- **AD-10 (Empacotamento OCI/Docker):** `ai-dev-executor` deve ser empacotado como imagem Docker independente e adicionado ao `docker-compose.yml`.
- **Política Zero Deferred Work:** Qualquer apontamento relevante identificado durante a revisão de código desta história deve ser imediatamente sanado no escopo do PR/história.

### Exemplo de Estrutura do Orquestrador de Sandbox (`executor/src/sandbox.py`)

```python
import docker
import os
import shutil
import tempfile
from typing import Dict, Optional, Generator
from contextlib import contextmanager

class DockerSandboxManager:
    def __init__(self, docker_client: Optional[docker.DockerClient] = None):
        self.client = docker_client or docker.from_env()

    @contextmanager
    def run_sandbox(self, image: str, command: str, env_vars: Optional[Dict[str, str]] = None) -> Generator[docker.models.containers.Container, None, None]:
        temp_dir = tempfile.mkdtemp(prefix="aidev_sandbox_")
        container = None
        try:
            volumes = {
                temp_dir: {'bind': '/workspace', 'mode': 'rw'}
            }
            container = self.client.containers.run(
                image=image,
                command=command,
                environment=env_vars or {},
                volumes=volumes,
                working_dir='/workspace',
                detach=True,
                auto_remove=False  # Gerenciado explicitamente no cleanup para resgate de logs em caso de erro
            )
            yield container
        finally:
            if container:
                try:
                    container.stop(timeout=5)
                except Exception:
                    pass
                try:
                    container.remove(v=True, force=True)
                except Exception:
                    pass
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
```

### Exemplo de Worker Loop com Graceful Shutdown (`executor/src/worker.py`)

```python
import asyncio
import signal
import logging
from persistence import EventRepository

logger = logging.getLogger("ai-dev-executor")

class ExecutorWorker:
    def __init__(self, repo: EventRepository, worker_id: str = "executor-worker-1"):
        self.repo = repo
        self.worker_id = worker_id
        self.running = False

    async def start(self):
        self.running = True
        logger.info(f"Worker {self.worker_id} iniciado.")
        while self.running:
            try:
                event = await self.repo.claim_event(["workflow.execution"], self.worker_id)
                if event:
                    logger.info(f"Evento {event['event_id']} reivindicado.")
                    await self._process_event(event)
                else:
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no loop do worker: {e}", exc_info=True)
                await asyncio.sleep(2)

    def stop(self):
        logger.info(f"Encerrando worker {self.worker_id} graciosamente...")
        self.running = False
```

### Estrutura de Arquivos Criada/Modificada

```text
{project-root}/
  docker-compose.yml                    # Adição do serviço ai-dev-executor com acesso ao docker.sock
  README.md                             # Documentação do ai-dev-executor e comandos de teste
  executor/
    Dockerfile                          # Imagem Docker multi-stage para Python 3.12
    pyproject.toml                      # Dependências e especificação do pacote do executor
    src/
      __init__.py
      config.py                         # Configurações do Executor via pydantic-settings
      sandbox.py                        # Orquestrador do container sandbox Docker
      worker.py                         # Loop de consumo e envio para sandbox
      main.py                           # Ponto de entrada do serviço e tratamento de sinais (SIGTERM/SIGINT)
  tests/
    executor/
      test_sandbox.py                   # Testes unitários com mock do Docker SDK
      test_worker.py                    # Testes do loop do worker e ciclo de vida
```

### Previous Story Intelligence

- **História 1.1 & 1.2:** Estruturas de banco de dados e ingestão FastAPI configuradas com SQLAlchemy async e Pydantic v2.
- **História 1.3:** `EventRepository` em `persistence/src/repository.py` exporta `claim_event`, `complete_event`, `fail_event` e `add_audit_log`. Os eventos consumidos pelo executor usam o tipo `workflow.execution`.
- **Épico 1 Retro:** Estabeleceu a política de "Zero Deferred Work" e demandou fixtures dedicadas para o `ai-dev-executor`.

### References

- [ARCHITECTURE-SPINE.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/architecture/architecture-AI%20Developer-2026-08-09/ARCHITECTURE-SPINE.md#L63-L67) - AD-6: Execução em Container Efêmero
- [ARCHITECTURE-SPINE.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/architecture/architecture-AI%20Developer-2026-08-09/ARCHITECTURE-SPINE.md#L83-L87) - AD-10: Empacotamento Docker
- [epics.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/epics.md#L147-L159) - Detalhes da História 2.1
- [1-3-roteamento-e-consumo-idempotente-via-trava-de-banco-skip-locked.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/implementation-artifacts/1-3-roteamento-e-consumo-idempotente-via-trava-de-banco-skip-locked.md) - Repositório de Eventos e SKIP LOCKED

---

## Dev Agent Record

### Agent Model Used

Gemini 3.6 Flash (High)

### Debug Log References

- Resolvida colisão de nome de pacote no pytest ajustando importação para pacotes raiz explícitos.
- Ajustado loop de sleep no worker para encerramento instantâneo via cancelamento de task no `stop()`.

### Completion Notes List

- Criada estrutura modular do serviço `ai-dev-executor` em `executor/src/` (`config.py`, `sandbox.py`, `worker.py`, `main.py`).
- Implementado `DockerSandboxManager` com contexto `run_sandbox`, suporte a diretórios/volumes temporários e teardown garantido via `stop()`, `remove(v=True, force=True)` e remoção de arquivos no host.
- Implementado `ExecutorWorker` integrando `EventRepository.claim_event` para eventos `workflow.execution` com transições atômicas, backoff exponencial configurável em períodos ociosos e cancelamento gracioso de sinais (`SIGTERM`/`SIGINT`).
- Criado `executor/Dockerfile` multi-stage e integrado serviço `ai-dev-executor` no `docker-compose.yml` com volume mount do `/var/run/docker.sock`.
- Criada suíte de testes automatizados unitários em `tests/executor/` (`test_sandbox.py` e `test_worker.py`), cobrindo mock do Docker SDK, resiliência de teardown, dispatch do worker, retenção de audit logs e graceful shutdown.
- Atualizado o `README.md` raiz detalhando o componente `ai-dev-executor`, variáveis de ambiente e instruções de teste.

### File List

- `executor/pyproject.toml`
- `executor/Dockerfile`
- `executor/__init__.py`
- `executor/src/__init__.py`
- `executor/src/config.py`
- `executor/src/sandbox.py`
- `executor/src/worker.py`
- `executor/src/main.py`
- `tests/executor/test_sandbox.py`
- `tests/executor/test_worker.py`
- `docker-compose.yml`
- `README.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `_bmad-output/implementation-artifacts/2-1-worker-de-orquestracao-do-executor-e-sandbox-docker-efemero-ai-dev-executor.md`

### Change Log

- **2026-08-12**: Implementação completa da história 2.1 (Módulo Executor, Orquestrador Sandbox, Worker Async, Docker Multi-stage, Docker Compose, Suíte de Testes e Documentação). Status alterado para `review`.

