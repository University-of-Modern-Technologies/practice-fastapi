FROM ghcr.io/astral-sh/uv:0.11.23-python3.13-trixie-slim AS dependencies
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv
COPY pyproject.toml uv.lock ./
# Only the runtime dependency set is installed; the lock file makes the result
# byte-for-byte reproducible.
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.13-slim-trixie AS runtime
ENV APP_ENV=production \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --create-home app
COPY --from=dependencies --chown=app:app /app/.venv /app/.venv
# The migration job runs from this same image, so the schema history and the
# seed have to ship with it.
# The running version is reported from here rather than duplicated in code.
COPY --chown=app:app pyproject.toml ./pyproject.toml
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app app ./app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
