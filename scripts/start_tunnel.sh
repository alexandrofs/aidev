#!/usr/bin/env bash

# ==============================================================================
# AI Developer - Script de Inicialização de Túnel para Webhooks GitHub
# Exponibiliza a porta 8000 (ai-dev-api) para a internet via túnel HTTPS seguro.
# ==============================================================================

set -e

PORT="${PORT:-8000}"
TOOL="${1:-auto}"

echo "========================================================"
echo "🚀 AI Developer - Iniciando Túnel para Webhook do GitHub"
echo "========================================================"

# 1. Verificar se a API local está ativa
if curl -s "http://localhost:${PORT}/healthz" > /dev/null 2>&1; then
    echo "✅ ai-dev-api está respondendo em http://localhost:${PORT}/healthz"
else
    echo "⚠️  Aviso: Não foi possível conectar em http://localhost:${PORT}/healthz."
    echo "👉 Certifique-se de que os containers estão rodando com: docker compose up -d"
    echo ""
fi

# 2. Instruções de configuração do GitHub Webhook
print_instructions() {
    local url="$1"
    echo ""
    echo "========================================================"
    echo "🎯 CONFIGURAÇÃO DO WEBHOOK NO GITHUB:"
    echo "========================================================"
    echo "1. Acesse o Repositório ou Organização no GitHub:"
    echo "   Settings -> Webhooks -> Add webhook"
    echo ""
    echo "2. Preencha os campos:"
    echo "   📍 Payload URL:  ${url}/webhooks/github"
    echo "   📦 Content type: application/json"
    echo "   🔑 Secret:       (o valor de GITHUB_WEBHOOK_SECRET do seu .env)"
    echo "   🔔 Events:       Selecione 'Issues', 'Issue comments', 'Projects v2 status update' (ou 'Send me everything')"
    echo "========================================================"
    echo ""
}

# 3. Detectar e executar a ferramenta de túnel
if [ "$TOOL" = "cloudflared" ] || ([ "$TOOL" = "auto" ] && command -v cloudflared &> /dev/null); then
    echo "🌐 Utilizando Cloudflare Tunnel (cloudflared)..."
    echo "💡 Pressione Ctrl+C para encerrar o túnel a qualquer momento."
    echo ""
    print_instructions "https://<SEU-DOMINIO-CLOUDFLARE>.trycloudflare.com"
    cloudflared tunnel --url "http://localhost:${PORT}"

elif [ "$TOOL" = "ngrok" ] || ([ "$TOOL" = "auto" ] && command -v ngrok &> /dev/null); then
    echo "🌐 Utilizando ngrok..."
    echo "💡 Pressione Ctrl+C para encerrar o túnel a qualquer momento."
    echo ""
    print_instructions "https://<SEU-DOMINIO-NGROK>.ngrok-free.app"
    ngrok http "${PORT}"

elif command -v npx &> /dev/null; then
    echo "🌐 Utilizando localtunnel (via npx)..."
    print_instructions "https://<SEU-DOMINIO-LOCALTUNNEL>.loca.lt"
    npx -y localtunnel --port "${PORT}"

else
    echo "❌ Nenhuma ferramenta de túnel encontrada (cloudflared, ngrok ou npx localtunnel)."
    echo "👉 Instale o cloudflared: brew install cloudflared"
    echo "👉 Ou instale o ngrok:      brew install ngrok"
    exit 1
fi
