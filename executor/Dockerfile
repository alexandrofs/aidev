FROM python:3.12-slim AS builder

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=100

# Instalar dependências da biblioteca persistence
COPY persistence /app/persistence
RUN pip install --no-cache-dir --default-timeout=100 ./persistence

# Instalar dependências do executor
COPY executor /app/executor
RUN pip install --no-cache-dir --default-timeout=100 ./executor

FROM python:3.12-slim

WORKDIR /app

# Copiar bibliotecas e binários compilados do estágio builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY persistence /app/persistence
COPY executor /app/executor

ENV PYTHONPATH=/app

CMD ["python", "-m", "executor.src.main"]
