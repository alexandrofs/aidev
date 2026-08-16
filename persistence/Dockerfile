FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .

RUN pip install --no-cache-dir .

COPY alembic.ini .
COPY entrypoint.sh .
COPY src/ ./src/

RUN chmod +x entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

ENTRYPOINT ["/app/entrypoint.sh"]
