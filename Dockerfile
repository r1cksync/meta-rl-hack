# IncidentCommander — HF Spaces Dockerfile
# Serves the OpenEnv HTTP API (reset/step/state) on port 7860

FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Python deps (lightweight — no torch/transformers for the server)
COPY rl-agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir \
    fastapi>=0.104.0 \
    uvicorn[standard]>=0.24.0 \
    pydantic>=2.5.0 \
    httpx>=0.25.0 \
    structlog>=23.2.0 \
    numpy>=1.26.0 \
    openai>=1.3.0 \
    boto3>=1.34.0

# Copy environment code
COPY rl-agent/environment /app/environment
COPY rl-agent/scenarios /app/scenarios
COPY rl-agent/server.py /app/server.py
COPY rl-agent/dashboard_pages.py /app/dashboard_pages.py
COPY rl-agent/dashboard.html /app/dashboard.html
COPY rl-agent/showcase.html /app/showcase.html
COPY rl-agent/showcase_data.json /app/showcase_data.json
COPY rl-agent/checkpoints /app/checkpoints
COPY openenv.yaml /app/openenv.yaml
COPY inference.py /app/inference.py

# HF Spaces exposes port 7860
ENV INCIDENT_COMMANDER_MOCK=true
ENV PORT=7860
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
