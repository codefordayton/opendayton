FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv

# Install dependencies first so source edits don't bust the layer cache.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY server ./server
COPY datasets ./datasets

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "/app/.venv/bin/uvicorn server.main:app --host 0.0.0.0 --port ${PORT}"]
