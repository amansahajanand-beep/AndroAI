# orchestration worker image. Build context: repository root.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY packages/contracts /app/packages/contracts
COPY workers/orchestration /app/workers/orchestration
RUN pip install --no-cache-dir /app/packages/contracts /app/workers/orchestration
CMD ["androai-orchestration"]
