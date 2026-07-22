# reports-svc — build context MUST be the repo root:
#   docker build -f services/reports/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# Shared contract models (monorepo local package)
COPY services/shared /shared
RUN pip install --no-cache-dir /shared

COPY services/reports/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Database schema contract (Single Source of Truth)
COPY contracts/database/schema.sql /app/schema.sql

COPY services/reports/app ./app

ENV PYTHONUNBUFFERED=1 \
    SCHEMA_PATH=/app/schema.sql \
    DATABASE_PATH=/data/reports.db

EXPOSE 8005

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
