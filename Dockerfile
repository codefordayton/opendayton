FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv

# Install dependencies first so source edits don't bust the layer cache.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# The County database is built monthly by .github/workflows/county-data.yml
# and published as a release asset (~90 MB). Baking it into the image keeps
# the running service stateless and read-only.
ADD https://github.com/codefordayton/opendayton/releases/download/county-data/county.duckdb /app/county/county.duckdb

COPY server ./server
COPY datasets ./datasets
COPY county/__init__.py county/cama.py county/cama_spec.json county/build.py ./county/

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "/app/.venv/bin/uvicorn server.main:app --host 0.0.0.0 --port ${PORT}"]
