# remediation-svc — approval-gated, typed Kubernetes changes.
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

COPY services/shared /shared
RUN pip install --no-cache-dir /shared

COPY services/remediation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/remediation/app ./app

ENV PYTHONUNBUFFERED=1

EXPOSE 8008

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8008"]
