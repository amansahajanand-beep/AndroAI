# orchestration worker image. Build context: repository root.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY packages/contracts /app/packages/contracts
COPY packages/agent-core/orchestration /app/packages/agent-core/orchestration
COPY workers/orchestration /app/workers/orchestration
RUN pip install --no-cache-dir /app/packages/contracts \
    "/app/packages/agent-core/orchestration[anthropic,openai,postgres]" /app/workers/orchestration
CMD ["androai-orchestration"]
