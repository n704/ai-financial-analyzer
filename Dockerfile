# syntax=docker/dockerfile:1

# --- Build stage: resolve deps and install the project into a venv ---
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Extras needed by *some* profile this image might run: gemini (dev.yaml's
# default LLM/embeddings), postgres + redis (scaled.yaml), storage (S3/MinIO
# in scaled.yaml). Not `offline` — that profile targets bare-metal per
# ARCHITECTURE.md §7, not this container. Not `forecast` either, by default:
# torch + TimesFM roughly double the image, so only the worker image in
# docker-compose.scaled.yml adds `--extra forecast` (ARCHITECTURE.md §7).
ARG PROFILE_EXTRAS="--extra gemini --extra postgres --extra redis --extra storage --extra parse"

# Cache dependency layer separately from source.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev $PROFILE_EXTRAS

COPY . .
RUN uv sync --frozen --no-dev $PROFILE_EXTRAS

# --- Runtime stage: copy the venv + source, no build tooling ---
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=builder /app /app
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["api"]
