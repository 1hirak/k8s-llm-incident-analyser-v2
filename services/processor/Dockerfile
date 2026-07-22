# processor-svc — build context MUST be the repo root:
#   docker build -f services/processor/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# Shared contract models (monorepo local package)
COPY services/shared /shared
RUN pip install --no-cache-dir /shared

COPY services/processor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/processor/app ./app

ENV PYTHONUNBUFFERED=1

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
