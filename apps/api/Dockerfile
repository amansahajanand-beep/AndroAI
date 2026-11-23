# Control-plane image. Build context: repository root.
# Deliberately contains NO Android SDK / JDK / Gradle.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY packages/contracts /app/packages/contracts
COPY packages/storage /app/packages/storage
COPY packages/android-tools /app/packages/android-tools
COPY apps/api /app/apps/api
RUN pip install --no-cache-dir /app/packages/contracts /app/packages/storage /app/packages/android-tools /app/apps/api

WORKDIR /app/apps/api
EXPOSE 8000
CMD ["uvicorn", "androai_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
