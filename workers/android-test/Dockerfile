# android-test worker image. Build context: repository root.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY packages/contracts /app/packages/contracts
COPY workers/android-test /app/workers/android-test
RUN pip install --no-cache-dir /app/packages/contracts /app/workers/android-test
# TODO(Person 4): install JDK + Android SDK + Gradle here (this image only,
# never the API image) and run as a non-root, network-restricted user.
CMD ["androai-android-test"]
