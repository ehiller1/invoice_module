# EIME PostgreSQL Setup

## Option 1: Docker (Recommended)

```bash
# Start PostgreSQL container
docker-compose up -d postgres

# Wait for health check to pass (5-10 seconds)
docker-compose ps

# Initialize database
cd backend
python -m db.init_db

# Verify connection
python -c "from db import test_connection; test_connection()"
```

## Option 2: Local PostgreSQL

```bash
# Install PostgreSQL 15+
# macOS: brew install postgresql@15
# Linux: apt install postgresql

# Start service
brew services start postgresql@15  # macOS
systemctl start postgresql         # Linux

# Create user and database
createuser -P claude  # Enter password: claude_dev
createdb -U claude eime_accounting

# Set .env DATABASE_URL
export DATABASE_URL="postgresql://claude:claude_dev@localhost:5432/eime_accounting"

# Initialize
cd backend
python -m db.init_db
```

## Verification

```bash
# Test connection
python -c "from db import test_connection; print(test_connection())"

# Check schema
psql -U claude -d eime_accounting -c "\dt"

# View record counts
psql -U claude -d eime_accounting -c "
  SELECT tablename, (SELECT COUNT(*) FROM pg_tables WHERE tablename=pg_tables.tablename) as rows
  FROM pg_tables WHERE schemaname='public'
"
```
