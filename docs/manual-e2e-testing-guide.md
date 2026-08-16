# 📘 Guia de Testes E2E de Histórias Multi-Stack (Java, Flutter, Python)

Este guia documenta como realizar testes integrados ponta a ponta (E2E) no ecossistema do **AI Developer**, simulando o ciclo completo de ingestão de webhooks, execução isolada em Sandbox Docker efêmero, pipeline de validação local e persistência de memória hierárquica.

---

## 🏗️ 1. Arquitetura e Suporte Multi-Tecnologia

O sistema foi concebido para ser **agnóstico de linguagem e framework**:

- **Isolamento por Imagem Docker (`image`)**: O container efêmero é instanciado a partir da imagem OCI correspondente à stack do projeto (ex: `eclipse-temurin:21-alpine` para Java, `dart:stable` ou `ghcr.io/cirruslabs/flutter:latest` para Flutter, `python:3.12-slim` para Python, `node:20-alpine` para TypeScript/React).
- **Injeção Dinâmica de Contexto**: O sandbox recebe MCPs, Skills e Prompts específicos da fase.
- **Validações Pré-Entrega (`validation_commands`)**: Cada tecnologia executa sua suíte de linters e testes nativos (ex: `mvn test`, `flutter test`, `pytest`).
- **Rastreabilidade e Memória**: Todas as evidências são gravadas em `audit_logs`, `agent_memory` no PostgreSQL e consolidadas no arquivo `.memlog.md`.

---

## ⚡ 2. Pré-Requisitos

Certifique-se de que os containers da infraestrutura local estejam em execução:

```bash
docker compose up -d
```

Verifique o status dos serviços com:
```bash
docker compose ps
```

Os seguintes serviços devem estar com status saudável (`healthy` / `Up`):
- `aidev-postgres` (PostgreSQL 16 na porta `5432`)
- `aidev-api` (FastAPI na porta `8000`)
- `aidev-executor` (Worker orquestrador de sandboxes)

---

## 🚀 3. Executando o Script de Teste Automatizado

Criamos o script utilitário [`scripts/test_story_execution.py`](file:///Users/alexandrofs/projects/aidev/scripts/test_story_execution.py) para automatizar o envio de webhooks assinados via HMAC-SHA256 e o monitoramento em tempo real do processamento.

### A. Teste de História Java (Spring Boot / JUnit)

```bash
.venv/bin/python scripts/test_story_execution.py --stack java
```

**O que este teste executa:**
- Cria evento para `JAVA-PAYMENT-01`.
- Sobe sandbox com `eclipse-temurin:21-alpine`.
- Executa compilação e validação Java/JUnit.
- Registra auditoria e memória de longo prazo.

---

### B. Teste de História Flutter (Dart / Widget Tests)

```bash
.venv/bin/python scripts/test_story_execution.py --stack flutter
```

**O que este teste executa:**
- Cria evento para `FLUTTER-UI-01`.
- Sobe sandbox com `dart:stable`.
- Executa análise estática e validação de Widgets Dart.
- Realiza teardown completo do container sem vazamento de recursos.

---

### C. Teste de História Python (FastAPI / Pytest)

```bash
.venv/bin/python scripts/test_story_execution.py --stack python
```

---

### D. Teste com História Customizada

Você pode passar parâmetros customizados para testar qualquer repositório ou tecnologia:

```bash
.venv/bin/python scripts/test_story_execution.py \
  --stack custom \
  --story-id "MY-FEATURE-42" \
  --title "Implementação de Recurso Customizado"
```

---

## 🔍 4. Como Verificar os Resultados e Evidências

### 1. Consultar os Eventos no PostgreSQL
```bash
docker compose exec postgres psql -U aidev -d aidev -c "SELECT event_id, event_type, status, retry_count, updated_at FROM events ORDER BY created_at DESC LIMIT 5;"
```

### 2. Verificar a Trilha de Auditoria (`audit_logs`)
```bash
docker compose exec postgres psql -U aidev -d aidev -c "SELECT action, actor, created_at FROM audit_logs ORDER BY created_at DESC LIMIT 10;"
```

### 3. Inspecionar a Memória Hierárquica (`agent_memory`)
```bash
docker compose exec postgres psql -U aidev -d aidev -c "SELECT story_id, memory_type, content FROM agent_memory ORDER BY created_at DESC LIMIT 5;"
```

### 4. Visualizar o Log Consolidado do Repositório
Abra o arquivo [`.memlog.md`](file:///Users/alexandrofs/projects/aidev/.memlog.md) na raiz do projeto para acompanhar os resumos diários adicionados pelo agente.

### 5. Inspecionar Logs em Tempo Real do Executor
```bash
docker compose logs -f ai-dev-executor
```

---

## 🧪 5. Execução da Suíte de Testes Unitários e de Integração

Para rodar todos os 110 testes automatizados da aplicação:

```bash
.venv/bin/pytest
```
