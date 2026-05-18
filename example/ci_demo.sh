#!/usr/bin/env bash
# Example CI workflow for the pysquirrel demo FastAPI app.
#
# Prerequisites:
#   - Postgres 16+ running with the demo schema applied
#   - pysquirrel installed (`pip install -e .` from the project root)
#   - DATABASE_URL set or PG* env vars configured
#
# This script demonstrates how `pysquirrel check` acts as a CI gate:
# it verifies that sql_generated.py is in sync with the .sql source files.

set -euo pipefail

echo "=== pysquirrel CI demo ==="
echo ""

# Step 1: Apply schema migrations (in a real CI pipeline, the DB already exists).
echo ">>> Applying schema migrations..."
psql "$DATABASE_URL" -f app/migrations/001_init.sql 2>/dev/null || true
echo ""

# Step 2: Generate the Python module from .sql files.
echo ">>> Running pysquirrel generate..."
pysquirrel generate --root app/ --database-url "$DATABASE_URL"
echo ""

# Step 3: Verify generated files are in sync (the CI gate).
echo ">>> Running pysquirrel check..."
if pysquirrel check --root app/ --database-url "$DATABASE_URL"; then
    echo "✅ check passed — generated files are in sync"
else
    echo "❌ check failed — generated files are out of sync"
    echo "   Run 'pysquirrel generate' to update them."
    exit 1
fi
echo ""

echo "=== CI demo complete ==="
