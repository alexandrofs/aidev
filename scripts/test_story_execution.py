#!/usr/bin/env python3
"""
Script de Teste E2E e Simulação de Histórias no AI Developer.
Permite testar a ingestão de webhooks e a orquestração do sandbox
para diferentes stacks (Java, Flutter, Python ou Customizada).
"""

import os
import sys
import time
import json
import uuid
import hmac
import hashlib
import argparse
import urllib.request
import urllib.error
from pathlib import Path


def load_env(env_path: Path) -> dict:
    """Carrega variáveis do arquivo .env se existir."""
    env_vars = {}
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip()
    return env_vars


def get_stack_payload(stack: str, story_id: str, title: str) -> dict:
    """Gera o payload específico para a tecnologia selecionada."""
    if stack == "java":
        return {
            "story_id": story_id or "JAVA-PAYMENT-01",
            "title": title or "Implementação de Microserviço de Pagamentos (Spring Boot / Java 21)",
            "image": "eclipse-temurin:21-alpine",
            "phases": ["coding"],
            "command": "java -version && echo '[SANDBOX] Compilação e código Java executados com sucesso!'",
            "validation_commands": [
                "java -version",
                "echo '[VALIDATION] 14 testes unitários JUnit / Mockito aprovados com sucesso!'"
            ],
            "repository": "alexandrofs/aidev"
        }
    elif stack == "flutter":
        return {
            "story_id": story_id or "FLUTTER-UI-01",
            "title": title or "Implementação de Interface de Checkout e Widgets (Flutter / Dart)",
            "image": "dart:stable",
            "entrypoint": ["/bin/sh", "-c"],
            "phases": ["coding"],
            "command": "dart --version && echo '[SANDBOX] Código Dart / Flutter estruturado com sucesso!'",
            "validation_commands": [
                "dart --version",
                "echo '[VALIDATION] Análise estática e 8 Widget tests aprovados com sucesso!'"
            ],
            "repository": "alexandrofs/aidev"
        }
    elif stack == "python":
        return {
            "story_id": story_id or "PY-SERVICE-01",
            "title": title or "Implementação de Módulo de Análise de Dados (FastAPI / Python)",
            "image": "python:3.12-slim",
            "phases": ["coding"],
            "command": "python3 -c \"print('[SANDBOX] Código Python executado com sucesso!')\"",
            "validation_commands": [
                "python3 -c \"print('[VALIDATION] Suíte de testes Pytest 100% aprovada!')\""
            ],
            "repository": "alexandrofs/aidev"
        }
    else:
        return {
            "story_id": story_id or f"CUSTOM-{uuid.uuid4().hex[:4].upper()}",
            "title": title or "Execução de História Customizada",
            "image": "python:3.12-slim",
            "phases": ["coding"],
            "command": "echo '[SANDBOX] Execução customizada em andamento...'",
            "validation_commands": [
                "echo '[VALIDATION] Testes de validação executados!'"
            ],
            "repository": "alexandrofs/aidev"
        }


def compute_signature(secret: str, body: bytes) -> str:
    """Calcula a assinatura HMAC-SHA256 padrão do GitHub."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def send_webhook(api_url: str, secret: str, payload: dict) -> tuple[int, dict]:
    """Envia a requisição de webhook assinada para a API."""
    delivery_id = str(uuid.uuid4())
    body = json.dumps(payload).encode("utf-8")
    signature = compute_signature(secret, body)

    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "workflow.execution",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": signature
    }

    req = urllib.request.Request(f"{api_url.rstrip('/')}/webhooks/github", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            res_body = json.loads(response.read().decode("utf-8"))
            return response.status, res_body
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(err_body)
        except Exception:
            return e.code, {"error": err_body}
    except Exception as e:
        return 500, {"error": str(e)}


def query_db_status(event_id: str) -> dict:
    """Consulta o banco de dados via docker compose para obter status em tempo real."""
    import subprocess
    cmd = [
        "docker", "compose", "exec", "-T", "postgres",
        "psql", "-U", "aidev", "-d", "aidev", "-t", "-A", "-F", "|",
        "-c", f"SELECT status, retry_count FROM events WHERE event_id = '{event_id}';"
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        if out:
            parts = out.split("|")
            return {"status": parts[0], "retry_count": int(parts[1]) if len(parts) > 1 else 0}
    except Exception:
        pass
    return {}


def query_audit_logs(event_id: str) -> list[tuple[str, str]]:
    """Obtém os logs de auditoria do evento."""
    import subprocess
    cmd = [
        "docker", "compose", "exec", "-T", "postgres",
        "psql", "-U", "aidev", "-d", "aidev", "-t", "-A", "-F", "|",
        "-c", f"SELECT action, actor FROM audit_logs WHERE event_id = '{event_id}' ORDER BY created_at ASC;"
    ]
    logs = []
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        if out:
            for line in out.splitlines():
                parts = line.split("|")
                if len(parts) >= 2:
                    logs.append((parts[0], parts[1]))
    except Exception:
        pass
    return logs


def main():
    parser = argparse.ArgumentParser(description="Testador de Execução de Histórias no AI Developer (Java, Flutter, Python)")
    parser.add_argument("--stack", choices=["java", "flutter", "python", "custom"], default="java",
                        help="Tecnologia/stack a ser simulada (padrão: java)")
    parser.add_argument("--story-id", type=str, default="", help="ID da história (ex: STORY-PAYMENT-01)")
    parser.add_argument("--title", type=str, default="", help="Título descritivo da história")
    parser.add_argument("--api-url", type=str, default="http://localhost:8000", help="URL base da API ai-dev-api")
    parser.add_argument("--secret", type=str, default="", help="Segredo do webhook (lê do .env se omitido)")
    parser.add_argument("--no-follow", action="store_true", help="Não aguarda a conclusão da execução no PostgreSQL")

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    env_vars = load_env(project_root / ".env")
    secret = args.secret or env_vars.get("GITHUB_WEBHOOK_SECRET", "mude-para-seu-segredo-real")

    payload = get_stack_payload(args.stack, args.story_id, args.title)

    print("\n" + "=" * 65)
    print(f" 🚀 DISPARANDO TESTE DE HISTÓRIA: STACK [{args.stack.upper()}]")
    print("=" * 65)
    print(f" • Story ID      : {payload['story_id']}")
    print(f" • Título        : {payload['title']}")
    print(f" • Imagem Docker : {payload['image']}")
    print(f" • Validações    : {payload['validation_commands']}")
    print(f" • API Endpoint  : {args.api_url}/webhooks/github")
    print("=" * 65)

    status_code, response = send_webhook(args.api_url, secret, payload)

    if status_code != 202:
        print(f"\n❌ Falha no envio do webhook (HTTP {status_code}):")
        print(json.dumps(response, indent=2, ensure_ascii=False))
        sys.exit(1)

    event_id = response.get("event_id")
    print(f"\n✅ Webhook aceito pela API (HTTP 202 Accepted)!")
    print(f" • Event ID: {event_id}")
    print(f" • Status Inicial: {response.get('status', 'PENDING')}")

    if args.no_follow:
        print("\n[--no-follow informado] Evento enviado. Verifique os logs do ai-dev-executor.")
        return

    print("\n⏳ Acompanhando ciclo de vida no Worker e PostgreSQL...")
    start_time = time.time()
    last_status = ""
    seen_audit_actions = set()

    while time.time() - start_time < 60:
        db_info = query_db_status(event_id)
        current_status = db_info.get("status", "UNKNOWN")

        if current_status != last_status:
            print(f"   ➔ Status atual: [{current_status}]")
            last_status = current_status

        # Exibir novas etapas de auditoria
        audit_logs = query_audit_logs(event_id)
        for action, actor in audit_logs:
            if action not in seen_audit_actions:
                print(f"     [AUDIT] {action} (por {actor})")
                seen_audit_actions.add(action)

        if current_status in ("COMPLETED", "FAILED"):
            break

        time.sleep(1.5)

    print("\n" + "=" * 65)
    if last_status == "COMPLETED":
        print(" 🎉 TESTE CONCLUÍDO COM SUCESSO!")
        print(f" • Evento {event_id} processado com status [COMPLETED].")
        print(" • Sandbox efêmero isolado e destruído sem contaminação.")
        print(" • Memória diária atualizada no PostgreSQL e .memlog.md.")
    elif last_status == "FAILED":
        print(" ❌ O TESTE FALHOU NA EXECUÇÃO DO SANDBOX OU VALIDAÇÃO.")
    else:
        print(f" ⚠️ Tempo limite de espera atingido. Status final observado: [{last_status}].")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
