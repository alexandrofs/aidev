FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

COPY alembic.ini .
COPY entrypoint.sh .
COPY src/ ./src/

RUN chmod +x entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

ENTRYPOINT ["/app/entrypoint.sh"]
