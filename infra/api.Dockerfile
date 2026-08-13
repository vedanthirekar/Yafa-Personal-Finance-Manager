# Multi-stage: resolve dependencies against the lockfile in a builder, then
# copy only the finished virtualenv into a slim runtime image.
#
# Build from the repo root:
#   docker build -f infra/api.Dockerfile -t yafa-api .

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer first, without the app source, so editing application code
# doesn't invalidate the (slow) dependency install.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

# The CPU torch wheel is what PyPI serves by default, which is what we want
# here -- GPU inference is a local-development concern, not a container one.

COPY apps/api ./apps/api
COPY ml ./ml
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.12-slim-bookworm AS runtime

# ffmpeg: faster-whisper decodes uploaded audio through it.
# libpq5: runtime shared library for psycopg.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Never run the app as root.
RUN groupadd --system --gid 1001 yafa \
    && useradd --system --uid 1001 --gid yafa --create-home yafa

WORKDIR /app

COPY --from=builder --chown=yafa:yafa /app/.venv /app/.venv
COPY --from=builder --chown=yafa:yafa /app/apps/api /app/apps/api
COPY --from=builder --chown=yafa:yafa /app/ml /app/ml

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/apps/api \
    HF_HOME=/models

RUN mkdir -p /models && chown yafa:yafa /models

USER yafa

EXPOSE 8000

# Migrations run at start so a fresh volume comes up with the schema applied.
# Single worker: each one loads its own copy of the embedding and Whisper
# models, so replicas belong at the orchestrator level, not in-process.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
