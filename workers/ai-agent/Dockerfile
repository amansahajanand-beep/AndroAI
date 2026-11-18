# ai-agent worker image. Build context: repository root.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY packages/contracts /app/packages/contracts
COPY workers/ai-agent /app/workers/ai-agent
RUN pip install --no-cache-dir /app/packages/contracts /app/workers/ai-agent
CMD ["androai-ai-agent"]
