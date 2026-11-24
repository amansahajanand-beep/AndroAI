# Web image. Build context: repository root (the app depends on packages/shared-types).
#   docker build -f apps/web/Dockerfile --build-arg BACKEND_URL=http://api:8000 .
# NOT VERIFIED in the authoring environment (no Docker available): run `docker compose build web` first.
FROM node:22-alpine AS build
WORKDIR /repo
COPY packages/shared-types ./packages/shared-types
COPY apps/web/package.json apps/web/package-lock.json ./apps/web/
WORKDIR /repo/apps/web
RUN npm ci --no-audit --no-fund
COPY apps/web ./
# next.config.ts bakes the /api rewrite target into the build.
ARG BACKEND_URL=http://api:8000
ARG NEXT_PUBLIC_API_MODE=live
ENV BACKEND_URL=$BACKEND_URL NEXT_PUBLIC_API_MODE=$NEXT_PUBLIC_API_MODE NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
WORKDIR /repo
COPY --from=build /repo/packages/shared-types ./packages/shared-types
COPY --from=build /repo/apps/web ./apps/web
WORKDIR /repo/apps/web
USER node
EXPOSE 3000
CMD ["npm", "start", "--", "-p", "3000"]
