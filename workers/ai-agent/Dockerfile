# ai-agent worker image. Build context: repository root.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# git is required by the codegen checkpoint manager (shadow repository).
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY packages/contracts /app/packages/contracts
COPY packages/agent-core/codegen /app/packages/agent-core/codegen
COPY workers/ai-agent /app/workers/ai-agent
RUN pip install --no-cache-dir /app/packages/contracts /app/packages/agent-core/codegen \
    /app/workers/ai-agent
CMD ["androai-ai-agent"]
