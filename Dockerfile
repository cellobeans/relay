FROM python:3.12-slim

# Copy the uv binary from its official image instead of pip-installing it.
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /bin/uv

WORKDIR /app

# Install dependencies first, in their own layer, so code edits don't trigger a full reinstall.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Put the venv's python/uvicorn/arq/alembic on PATH.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Default command runs the API; docker-compose.yml overrides it for the worker and receiver.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
