#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting ai-dev-migrations entrypoint (working dir: $SCRIPT_DIR)..."

python3 - << 'EOF'
import sys
import time
import os
import socket
from urllib.parse import urlparse

host = os.getenv("POSTGRES_HOST", "localhost")
port = int(os.getenv("POSTGRES_PORT", "5432"))
db_url = os.getenv("DATABASE_URL")
max_retries = int(os.getenv("MAX_RETRIES", "30"))

if db_url:
    try:
        # Handle postgres:// or postgresql+psycopg:// schemes for urlparse
        normal_url = db_url
        if "://" in normal_url and not normal_url.startswith("http"):
            scheme, rest = normal_url.split("://", 1)
            normal_url = f"http://{rest}"
        parsed = urlparse(normal_url)
        if parsed.hostname:
            host = parsed.hostname
        if parsed.port:
            port = parsed.port
    except Exception as e:
        print(f"Warning: Failed to parse DATABASE_URL ({e}). Using target {host}:{port}")

print(f"Waiting for PostgreSQL at {host}:{port} (max retries: {max_retries})...")

connected = False
for attempt in range(1, max_retries + 1):
    try:
        with socket.create_connection((host, port), timeout=3):
            print(f"PostgreSQL at {host}:{port} is reachable! (Attempt {attempt})")
            connected = True
            break
    except (socket.error, OSError) as err:
        print(f"Attempt {attempt}/{max_retries}: PostgreSQL not ready yet ({err}). Waiting 2s...")
        time.sleep(2)

if not connected:
    print(f"ERROR: Could not connect to PostgreSQL at {host}:{port} after {max_retries} attempts.")
    sys.exit(1)

EOF

if [ $? -ne 0 ]; then
    echo "PostgreSQL wait failed. Exiting with status 1."
    exit 1
fi

echo "Running database migrations via Alembic..."
alembic upgrade head

if [ $? -eq 0 ]; then
    echo "Migrations applied successfully! Exiting with status 0."
    exit 0
else
    echo "ERROR: Migrations failed! Exiting with status 1."
    exit 1
fi
