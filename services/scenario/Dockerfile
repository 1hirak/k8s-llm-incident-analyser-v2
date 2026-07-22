# scenario-svc — build context MUST be the repo root:
#   docker build -f services/scenario/Dockerfile .
FROM python:3.12-slim

ARG KUBECTL_VERSION=v1.31.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL -o /usr/local/bin/kubectl \
       "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
    && chmod +x /usr/local/bin/kubectl \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Shared contract models (monorepo local package)
COPY services/shared /shared
RUN pip install --no-cache-dir /shared

COPY services/scenario/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/scenario/app ./app

# Bake fault scenarios, base manifests, and ground-truth metadata into the
# image so the service works in-cluster without host volume mounts.
# (docker-compose overrides these with live repo mounts for local dev.)
COPY k8s/scenarios /k8s/scenarios
COPY k8s/base /k8s/base
COPY evaluation/ground_truth /evaluation/ground_truth

ENV PYTHONUNBUFFERED=1 \
    SCENARIOS_DIR=/k8s/scenarios \
    BASE_DIR=/k8s/base \
    GROUND_TRUTH_DIR=/evaluation/ground_truth

EXPOSE 8006

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
