# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=9000

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code + bundled source the agent reads for RCA + demo alert scenarios.
COPY app ./app
COPY app_under_test ./app_under_test
COPY alerts ./alerts

# ddtrace ships a runtime entrypoint (ddtrace-run) but we enable LLMObs in-process
# (agentless) so no local Datadog Agent is required at the hackathon.
ENV APP_SOURCE_DIR=/app/app_under_test \
    AUTH_SERVICE_URL=http://auth-service:8080 \
    DD_SERVICE=sre-incident-agent \
    DD_ENV=hackathon \
    DD_LLMOBS_ML_APP=sre-incident-agent

EXPOSE 9000

# Run as non-root for EKS security posture.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

HEALTHCHECK --interval=10s --timeout=3s --retries=6 --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:9000/healthz').status==200 else 1)" || exit 1

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "9000"]
