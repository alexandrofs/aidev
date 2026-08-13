---
baseline_commit: 21141d17a33fa8d14a68ec8c4f50e74ae6a49315
---

# Story 2.2: Injeção Dinâmica de Contexto (MCPs, Skills e Prompts)

Status: done

## Story

As a agente AI Developer,
I want ter acesso às ferramentas MCP configuradas, Skills localizadas no repositório (`.agents/skills/`) e Templates de Prompts versionados dentro do sandbox efêmero,
so that minhas ações de código e planejamento respeitem rigorosamente a arquitetura, as regras de negócio e os padrões do projeto.

## Acceptance Criteria

1. **Descoberta e Carregamento de Servidores e Ferramentas MCP (AC: 1)**
   - **Given** um evento de execução reivindicado pelo worker `ai-dev-executor`
   - **When** a sessão de contexto for preparada pelo `ContextLoader` (`executor/src/context_loader.py`)
   - **Then** o sistema deve carregar e validar a configuração de servidores MCP (ex: via `mcp_config.json` ou variável/diretório de configuração) e injetá-la no pacote de contexto do sandbox
   - **And** em caso de falha de parsing ou JSON inválido no arquivo de configuração MCP, o carregamento deve falhar graciosamente com log descritivo indicando o erro.

2. **Mapeamento e Injeção de Skills Localizadas (`.agents/skills/`) (AC: 2)**
   - **Given** o repositório clonado ou montado no workspace do sandbox
   - **When** o ciclo de injeção de contexto for executado
   - **Then** o `ContextLoader` deve varrer o diretório `.agents/skills/`, validar a presença dos arquivos de instrução `SKILL.md` (ou metadados YAML/frontmatter) e disponibilizar a biblioteca de skills para o agente dentro do container sandbox
   - **And** garantir suporte a varredura dinâmica sem falhar caso o diretório esteja vazio ou contenha subdiretórios adicionais de skills customizadas.

3. **Validação Rigorosa e Carregamento de Templates de Prompts Versionados (AC: 3)**
   - **Given** a preparação da sessão da engine LLM para as diferentes fases do workflow (`planning`, `coding`, `review`)
   - **When** o `ContextLoader` carregar os templates de prompts do diretório de prompts (`executor/prompts/`)
   - **Then** os prompts correspondentes a cada fase devem ser lidos e validados
   - **And** a execução deve ser abortada imediatamente com exceção explícita (`MandatoryPromptMissingError` / `PromptTemplateNotFoundError`) com mensagem de erro clara caso um template obrigatório (ex: `planning.md`, `coding.md`, `review.md`) esteja ausente ou vazio, impedindo execuções com contexto incompleto.

4. **Integração do ContextLoader ao `DockerSandboxManager` e `ExecutorWorker` (AC: 4)**
   - **Given** o worker `ExecutorWorker` em `executor/src/worker.py`
   - **When** um evento `workflow.execution` for consumido do PostgreSQL
   - **Then** o worker deve invocar o `ContextLoader` para compilar o envelope de contexto contendo MCPs, Skills catalogadas e Prompts da fase
   - **And** repassar esse pacote de contexto para o `DockerSandboxManager` em `executor/src/sandbox.py`, garantindo que os diretórios efêmeros do container sandbox recebam os arquivos de contexto montados em `/workspace/.agents/skills/` e `/workspace/prompts/` com variáveis de ambiente configuradas.

5. **Suíte de Testes Automatizados Unitários e de Integração (AC: 5)**
   - **Given** as novas classes `ContextLoader`, `PromptTemplateNotFoundError` e o orquestrador atualizado
   - **When** a suíte de testes em `tests/executor/` for executada via `pytest`
   - **Then** os testes devem cobrir:
     - Leitura e validação de `mcp_config.json` válido e inválido
     - Varredura e catálogo de skills em `.agents/skills/`
     - Validação de erro impeditivo quando um prompt obrigatório (`planning.md`, `coding.md`, `review.md`) estiver ausente ou vazio
     - Integração do envelope de contexto gerado pelo `ContextLoader` com `DockerSandboxManager.run_sandbox` e `ExecutorWorker._process_event`
     - 100% de passagem de todos os testes existentes e novos sem regressão.

---

## Tasks / Subtasks

- [x] Task 1: Módulo de Configuração e Exceções de Contexto (`executor/src/config.py` e `executor/src/exceptions.py`) (AC: 3)
  - [x] Atualizar `ExecutorSettings` em `executor/src/config.py` adicionando `MCP_CONFIG_PATH`, `SKILLS_DIR`, `PROMPTS_DIR`, e `MANDATORY_PROMPTS` (`["planning.md", "coding.md", "review.md"]`)
  - [x] Criar `executor/src/exceptions.py` com exceções customizadas: `ContextError`, `PromptTemplateNotFoundError`, `InvalidMCPConfigError`

- [x] Task 2: Implementação do `ContextLoader` (`executor/src/context_loader.py`) (AC: 1, 2, 3)
  - [x] Criar classe `ContextLoader` responsável por:
    - `load_mcp_config()`: ler e validar arquivo `mcp_config.json` ou dict de servidores MCP
    - `discover_skills()`: listar e validar diretórios em `.agents/skills/` contendo `SKILL.md`
    - `load_prompt_template(phase: str)`: ler prompt da fase (`planning`, `coding`, `review`), validando existência e conteúdo não-vazio; lançar `PromptTemplateNotFoundError` se ausente
    - `build_context_bundle(phase: str)`: compilar o bundle completo com MCPs, Skills e Prompts para consumo do sandbox

- [x] Task 3: Criação dos Prompt Templates Padrão (`executor/prompts/`) (AC: 3)
  - [x] Criar diretório `executor/prompts/`
  - [x] Criar template `executor/prompts/planning.md` (instruções estruturadas para fase de planejamento)
  - [x] Criar template `executor/prompts/coding.md` (instruções estruturadas para fase de desenvolvimento/código)
  - [x] Criar template `executor/prompts/review.md` (instruções estruturadas para fase de code review e auditoria de qualidade)

- [x] Task 4: Integração com `DockerSandboxManager` e `ExecutorWorker` (`executor/src/sandbox.py` e `executor/src/worker.py`) (AC: 4)
  - [x] Atualizar `DockerSandboxManager.run_sandbox` para aceitar `context_bundle` e montar volumes/arquivos adicionais no sandbox (`/workspace/.agents/skills`, `/workspace/prompts/`)
  - [x] Atualizar `ExecutorWorker._process_event` em `executor/src/worker.py` para invocar `ContextLoader.build_context_bundle(phase)` antes da execução no sandbox, tratando falhas de contexto com registro de audit log e status `FAILED` se prompt obrigatório estiver ausente.

- [x] Task 5: Suíte de Testes Automatizados em `tests/executor/` (AC: 5)
  - [x] Criar `tests/executor/test_context_loader.py` cobrindo carregamento de MCPs, varredura de Skills, carregamento de Prompts e exceção `PromptTemplateNotFoundError` em prompts ausentes.
  - [x] Atualizar `tests/executor/test_sandbox.py` e `tests/executor/test_worker.py` para testar a injeção do `context_bundle` no sandbox efêmero.
  - [x] Executar `pytest` para garantir 100% de aprovação de toda a suíte de testes.

### Review Findings

- [x] [Review][Patch] Substituição do fatiamento bruto `[:-3]` por `Path(p).stem` no `ContextLoader` [`executor/src/context_loader.py`:L92,L109]
- [x] [Review][Patch] Garantia de sobrescrita explícita da chave do prompt da fase em `run_sandbox` [`executor/src/sandbox.py`:L81]
- [x] [Review][Patch] Sanitização contra travessia de diretórios no método `load_prompt_template` [`executor/src/context_loader.py`:L67]
- [x] [Review][Patch] Reforço das asserções no teste `test_worker_invalid_payload` [`tests/executor/test_worker.py`:L178]
- [x] [Review][Defer] Resolução de caminhos relativos de configuração baseados no CWD [`executor/src/config.py`:L22-L24] — deferred, pre-existing


---

## Dev Notes

### Guardrails de Arquitetura & Invariantes

- **AD-9 (Extensibilidade do Executor via MCPs, Skills e Prompts):**
  - O executor deve injetar dinamicamente em cada sessão do sandbox:
    1. Servidores e ferramentas MCP configurados para o ambiente.
    2. Skills e customizações descobertas no repositório (`.agents/skills/`).
    3. Templates de prompts estruturados e versionados para as fases de planejamento (`planning`), desenvolvimento (`coding`) e revisão (`review`).
- **AD-6 (Sandbox Docker Efêmero):**
  - Os arquivos de contexto montados ou injetados (skills e prompts) residem dentro do workspace/volume efêmero do container sandbox, garantindo isolamento total em relação ao host.
- **AD-2 (Consumo via PostgreSQL com `SKIP LOCKED`):**
  - O worker `ai-dev-executor` consome eventos do PostgreSQL e prepara a injeção de contexto como primeira etapa do processamento do job.
- **Validação de Prompts Obrigatórios:**
  - Se qualquer prompt listado em `MANDATORY_PROMPTS` (`planning.md`, `coding.md`, `review.md`) estiver ausente ou for um arquivo de 0 bytes, o `ContextLoader` DEVE lançar `PromptTemplateNotFoundError`, fazendo com que a execução falhe com aviso legível antes de invocar a engine LLM.

### Análise dos Arquivos Existentes a Serem Modificados

- [`executor/src/config.py`](file:///Users/alexandrofs/projects/aidev/executor/src/config.py):
  - Preservar todas as variáveis existentes (`DOCKER_SOCKET`, `SANDBOX_IMAGE`, `POLL_INTERVAL`, `POSTGRES_*`).
  - Adicionar novas configurações para contexto:
    - `MCP_CONFIG_PATH: str = "mcp_config.json"`
    - `SKILLS_DIR: str = ".agents/skills"`
    - `PROMPTS_DIR: str = "executor/prompts"`
    - `MANDATORY_PROMPTS: list[str] = ["planning.md", "coding.md", "review.md"]`
- [`executor/src/sandbox.py`](file:///Users/alexandrofs/projects/aidev/executor/src/sandbox.py):
  - Atualizar `run_sandbox` / `execute_job` para aceitar um argumento opcional `context_bundle: Optional[Dict[str, Any]] = None`.
  - Quando fornecido, copiar ou montar a estrutura de skills e prompts no diretório efêmero `temp_dir` (`/workspace/.agents/skills` e `/workspace/prompts/`), garantindo permissões adequadas e cleanup automático em `cleanup_sandbox`.
- [`executor/src/worker.py`](file:///Users/alexandrofs/projects/aidev/executor/src/worker.py):
  - No método `_process_event`, instanciar o `ContextLoader`, determinar a fase do workflow (ex: `payload.get("phase", "coding")`), invocar `build_context_bundle(phase)` e repassar o pacote para `execute_job`.
  - Capturar exceções de `ContextError` / `PromptTemplateNotFoundError` e atualizar o estado do evento para `FAILED` com mensagem de erro explicativa.

### Dependências e Pacientes a Interagir

- `pydantic` / `pydantic-settings`
- `pathlib` / `json` para parsing e leitura de arquivos
- `docker` SDK para montagem de volumes efêmeros
- `pytest` com fixtures para simular arquivos de prompt/skills temporários

### Intelligence das Histórias Anteriores

- **História 2.1:** Estabeleceu `DockerSandboxManager` com `run_sandbox` e `cleanup_sandbox`, e o worker async em `ExecutorWorker` com `claim_event`.
- **Ação em Aberto no `sprint-status.yaml`:**
  - `epic: 1`, `action: "Validar contrato de injeção de MCPs, Skills e Prompts para a Historia 2.2"` (John) -> Atendida integralmente pela especificação desta história.

### References

- [ARCHITECTURE-SPINE.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/architecture/architecture-AI%20Developer-2026-08-09/ARCHITECTURE-SPINE.md#L78-L82) - AD-9: Extensibilidade do Executor via MCPs, Skills e Prompts
- [epics.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/planning-artifacts/epics.md#L160-L173) - Detalhes da História 2.2
- [2-1-worker-de-orquestracao-do-executor-e-sandbox-docker-efemero-ai-dev-executor.md](file:///Users/alexandrofs/projects/aidev/_bmad-output/implementation-artifacts/2-1-worker-de-orquestracao-do-executor-e-sandbox-docker-efemero-ai-dev-executor.md) - História 2.1 (Base do Executor)

---

## Dev Agent Record

### Agent Model Used

Gemini 3.6 Flash (High)

### Debug Log References

### Completion Notes List

- Implementado `ExecutorSettings` em `executor/src/config.py` com `MCP_CONFIG_PATH`, `SKILLS_DIR`, `PROMPTS_DIR` e `MANDATORY_PROMPTS`.
- Criado módulo de exceções `executor/src/exceptions.py` com `ContextError`, `PromptTemplateNotFoundError` e `InvalidMCPConfigError`.
- Implementado `ContextLoader` em `executor/src/context_loader.py` suportando carregamento resiliente de MCPs (`mcp_config.json`), catálogo dinâmico de skills em `.agents/skills/` com `SKILL.md` e validação estrita de prompts de workflow (`planning`, `coding`, `review`).
- Criados templates padrão de prompts em `executor/prompts/` (`planning.md`, `coding.md`, `review.md`).
- Atualizado `DockerSandboxManager` (`sandbox.py`) para aceitar `context_bundle` e injetar arquivos e variáveis de ambiente no container efêmero (`/workspace/mcp_config.json`, `/workspace/.agents/skills`, `/workspace/prompts`).
- Atualizado `ExecutorWorker` (`worker.py`) para compilar o envelope de contexto via `ContextLoader` antes da execução e tratar erros impeditivos de contexto como status `FAILED`.
- Criada e atualizada suíte de testes em `tests/executor/` (`test_context_loader.py`, `test_sandbox.py`, `test_worker.py`) cobrindo 100% dos cenários e critério de aceite com aprovação total de 22 testes unitários e de integração.

### File List

- `executor/src/config.py`
- `executor/src/exceptions.py`
- `executor/src/context_loader.py`
- `executor/src/sandbox.py`
- `executor/src/worker.py`
- `executor/prompts/planning.md`
- `executor/prompts/coding.md`
- `executor/prompts/review.md`
- `tests/executor/test_context_loader.py`
- `tests/executor/test_sandbox.py`
- `tests/executor/test_worker.py`
- `_bmad-output/implementation-artifacts/2-2-injecao-dinamica-de-contexto-mcps-skills-e-prompts.md`

### Change Log

- 2026-08-12: Implementação concluída da História 2.2 - Injeção Dinâmica de Contexto (MCPs, Skills e Prompts). Todos os testes passando sem regressões.

