FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    AUTH_MODE=oidc \
    DEMO_MODE=false \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    DATABASE_SSL_CA_FILE=/app/rds-ca-bundle.pem \
    ARTIFACT_STORAGE_PATH=/tmp/artifacts

WORKDIR /app
RUN python -m pip install --no-cache-dir --disable-pip-version-check uv==0.11.17
RUN python -c "import ssl, urllib.request; from pathlib import Path; Path('rds-ca-bundle.pem').write_bytes(urllib.request.urlopen('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem', timeout=30).read()); ssl.create_default_context(cafile='rds-ca-bundle.pem')"
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --extra aws --no-install-project
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
RUN groupadd --gid 10001 erpfusion \
    && useradd --uid 10001 --gid 10001 --no-create-home erpfusion \
    && mkdir -p /tmp/artifacts \
    && chown 10001:10001 /tmp/artifacts

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
