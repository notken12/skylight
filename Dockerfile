FROM node:22-bookworm-slim AS frontend

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    XDG_CACHE_HOME=/app/output/cache \
    HF_HOME=/app/output/cache/huggingface \
    TORCH_HOME=/app/output/cache/torch \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache

COPY *.py ./
COPY data/camera_view_samples/ ./data/camera_view_samples/
COPY data/sunset_view_samples/ ./data/sunset_view_samples/
COPY --from=frontend /app/frontend/dist/ ./frontend/dist/

RUN useradd --user-group --uid 10001 --create-home skylight \
    && install -d -o skylight -g skylight /app/output
USER skylight

EXPOSE 8765
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8765"]
