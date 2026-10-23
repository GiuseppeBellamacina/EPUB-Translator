FROM python:3.12-slim AS base

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Metric-compatible fonts used to re-typeset translated PDF text:
# Carlito = Calibri, Caladea = Cambria, Liberation = Arial/Times/Courier
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/strip_ligatures.py /tmp/strip_ligatures.py
RUN uvx --from fonttools python /tmp/strip_ligatures.py \
        /usr/share/fonts/truetype/crosextra /usr/share/fonts/truetype/liberation \
        /usr/local/share/fonts/pdf \
    && rm -rf /tmp/strip_ligatures.py /root/.cache/uv

# Keep the venv outside /app so the dev bind-mount of the source does not hide it
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    TRANSLATIO_DATA_DIR=/data \
    TRANSLATIO_CONFIG_FILE=/config/config.yaml

COPY pyproject.toml uv.lock* ./

# --- dev: test/lint tooling, source is bind-mounted by docker-compose.dev.yml ---
FROM base AS dev
RUN uv sync --extra dev --no-install-project
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# --- prod ---
FROM base AS prod
RUN uv sync --no-dev --no-install-project
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
