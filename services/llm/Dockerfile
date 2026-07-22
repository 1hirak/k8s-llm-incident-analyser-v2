# llm-svc — build context MUST be the repo root:
#   docker build -f services/llm/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# Shared contract models (monorepo local package)
COPY services/shared /shared
RUN pip install --no-cache-dir /shared

COPY services/llm/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/llm/app ./app

ENV PYTHONUNBUFFERED=1

EXPOSE 8004

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
