# syntax=docker/dockerfile:1.7
# Multi-stage image: dependencies from uv.lock, INT8 ONNX model baked into a layer so cold
# starts on Azure Container Apps (scale-to-zero) never download it. Runs as non-root.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# --- model: fetch the pinned INT8 ONNX export once, at build time --------------------------
FROM ${PYTHON_IMAGE} AS model
RUN pip install --no-cache-dir "huggingface-hub>=0.26,<1.0"
WORKDIR /build
COPY scripts/download_model.py scripts/download_model.py
RUN python scripts/download_model.py --out /models/multilingual-e5-small

# --- builder: resolve the locked runtime environment -------------------------------------
FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra data --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra data --no-editable

# --- runtime ---------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=model /models /app/models
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts/ingest.py ./scripts/ingest.py
COPY data/catalog.parquet ./data/catalog.parquet
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SKUMATCH_MODEL_DIR=/app/models/multilingual-e5-small \
    SKUMATCH_EMBEDDING_THREADS=1 \
    OMP_NUM_THREADS=1
USER 10001
EXPOSE 8000
CMD ["uvicorn", "skumatch.api.app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--no-access-log", "--timeout-graceful-shutdown", "20"]
