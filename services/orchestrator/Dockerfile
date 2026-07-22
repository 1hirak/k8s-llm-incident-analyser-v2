# orchestrator-svc — build context MUST be the repo root:
#   docker build -f services/orchestrator/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# Shared contract models (monorepo local package)
COPY services/shared /shared
RUN pip install --no-cache-dir /shared

COPY services/orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/orchestrator/app ./app

ENV PYTHONUNBUFFERED=1

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
