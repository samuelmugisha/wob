# Hugging Face Docker Space: the whole stack in one container (PostgreSQL + pgvector, ClamAV,
# the API, the ingestion worker and the web UI). See docs/operations/huggingface.md.
# hub.py push-space copies this file to the root of the Space repository, next to backend/,
# frontend/ and space/.

FROM node:22.20.0-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Rewrites are fixed at build time: the browser talks to Next.js, which proxies /api here.
ENV API_URL=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npm prune --omit=dev && npm cache clean --force


FROM python:3.12-slim-bookworm

# PostgreSQL 17 + pgvector (as on the server), Tesseract for OCR, ClamAV for malware scanning.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
       tesseract-ocr tesseract-ocr-eng clamav clamav-daemon \
    && install -d /usr/share/postgresql-common/pgdg /etc/postgresql-common/createcluster.d \
    && echo 'create_main_cluster = false' > /etc/postgresql-common/createcluster.d/no-main.conf \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
       https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17 postgresql-17-pgvector \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as uid 1000.
RUN useradd -m -u 1000 user && install -d -o user -g user /data /opt/clamav-seed

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv
COPY --from=web /usr/local/bin/node /usr/local/bin/node

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:/usr/lib/postgresql/17/bin:$PATH" \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken \
    HOME=/home/user \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --extra local-embeddings --no-install-project
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
COPY backend/ ./

COPY --from=web --chown=user:user /web/package.json /web/next.config.ts /app/frontend/
COPY --from=web --chown=user:user /web/node_modules /app/frontend/node_modules
COPY --from=web --chown=user:user /web/.next /app/frontend/.next

COPY space/ /app/space/
RUN chmod +x /app/space/start.sh

USER user
# Bake in the virus signatures so start-up doesn't depend on the ClamAV mirror; start.sh copies
# them to /data/clamav and freshclam keeps them current from there.
RUN freshclam --config-file=/app/space/freshclam.conf --datadir=/opt/clamav-seed \
    || echo "signatures will be downloaded at start-up"

EXPOSE 7860
CMD ["/app/space/start.sh"]
