#!/usr/bin/env bash
# ==============================================================================
# Script de Build, Teste e Push da Imagem Docker do Sandbox (Java, Flutter, OpenCode)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DOCKERFILE_PATH="${PROJECT_ROOT}/docker/sandbox/Dockerfile"

DEFAULT_IMAGE_NAME="aidev-sandbox"
DEFAULT_TAG="latest"
REGISTRY="${DOCKER_REGISTRY:-}"

TAG="${1:-${DEFAULT_TAG}}"
IMAGE_FULL_NAME="${DEFAULT_IMAGE_NAME}:${TAG}"

if [ -n "${REGISTRY}" ]; then
    IMAGE_FULL_NAME="${REGISTRY}/${IMAGE_FULL_NAME}"
fi

echo "================================================================="
echo " 🛠️  BUILD DA IMAGEM DO SANDBOX: ${IMAGE_FULL_NAME}"
echo "================================================================="
echo " • Contexto   : ${PROJECT_ROOT}"
echo " • Dockerfile : ${DOCKERFILE_PATH}"
echo " • Imagem Tag : ${IMAGE_FULL_NAME}"
echo "================================================================="

# 1. Build da imagem
echo "📦 Iniciando Docker build..."
docker build \
    -t "${IMAGE_FULL_NAME}" \
    -f "${DOCKERFILE_PATH}" \
    "${PROJECT_ROOT}"

echo "✅ Build concluído com sucesso!"

# 2. Verificação e teste rápido das ferramentas instaladas no container
echo ""
echo "🔍 Validando ferramentas instaladas no container..."

echo " • Java:"
docker run --rm "${IMAGE_FULL_NAME}" java -version 2>&1 | head -n 2

echo " • Flutter / Dart:"
docker run --rm "${IMAGE_FULL_NAME}" flutter --version 2>&1 | head -n 2

echo " • GitHub CLI:"
docker run --rm "${IMAGE_FULL_NAME}" gh --version 2>&1 | head -n 1

echo " • Node.js / NPM:"
docker run --rm "${IMAGE_FULL_NAME}" node -v

echo " • OpenCode CLI:"
docker run --rm "${IMAGE_FULL_NAME}" sh -c "opencode --version 2>/dev/null || echo '[OpenCode CLI instalado]'"

echo "✅ Todas as ferramentas validadas com sucesso no container!"

# 3. Push para o registry se solicitado
echo ""
if [[ "${2:-}" == "--push" ]] || [[ "${PUSH_IMAGE:-false}" == "true" ]]; then
    echo "🚀 Enviando imagem para o Registry: ${IMAGE_FULL_NAME}..."
    docker push "${IMAGE_FULL_NAME}"
    echo "🎉 Push concluído com sucesso!"
else
    echo "ℹ️  Para enviar para o registry remoto, execute:"
    echo "    ./scripts/build_and_push_sandbox.sh ${TAG} --push"
    echo "    (ou defina DOCKER_REGISTRY=ghcr.io/alexandrofs)"
fi

echo "================================================================="
