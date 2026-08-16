# Dockerfile do Sandbox Multi-Stack: Java Temurin, Flutter e OpenCode
# Base oficial Eclipse Temurin JDK 21 (LTS) baseado em Ubuntu Jammy
FROM eclipse-temurin:21-jdk-jammy

LABEL maintainer="AI Developer Team"
LABEL description="Sandbox isolado multi-stack para Java, Flutter, Python e OpenCode AI Agent"

ENV DEBIAN_FRONTEND=noninteractive
ENV SHELL=/bin/bash

# 1. Instalação de Utilitários Base, Compiladores, Python, Maven e Gradle
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    wget \
    git \
    unzip \
    xz-utils \
    zip \
    libglu1-mesa \
    build-essential \
    ca-certificates \
    gnupg \
    jq \
    python3 \
    python3-pip \
    python3-venv \
    maven \
    gradle \
    clang \
    cmake \
    ninja-build \
    pkg-config \
    libgtk-3-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Instalação do GitHub CLI (gh)
RUN mkdir -p -m 755 /etc/apt/keyrings && \
    wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null && \
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

# 3. Instalação do Node.js (v20 LTS) e CLI do OpenCode
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g opencode-ai opencode || npm install -g opencode-ai || true && \
    rm -rf /var/lib/apt/lists/*

# 4. Instalação e Configuração do Flutter SDK (Stable)
ENV FLUTTER_HOME=/opt/flutter
RUN git clone --depth 1 -b stable https://github.com/flutter/flutter.git $FLUTTER_HOME && \
    git config --global --add safe.directory $FLUTTER_HOME

ENV PATH="$FLUTTER_HOME/bin:$FLUTTER_HOME/bin/cache/dart-sdk/bin:$PATH"

# Pre-cache de artefatos essenciais do Flutter
RUN flutter config --no-analytics && \
    flutter precache --universal

# 5. Configuração do Diretório de Trabalho do Sandbox
WORKDIR /workspace
RUN git config --global --add safe.directory /workspace

CMD ["/bin/bash"]
