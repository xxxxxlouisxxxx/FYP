# HOP platform image: API (default), CLI and Streamlit dashboard share one image.
# Build from the repository root:  docker build -f infrastructure/containers/Dockerfile -t hop-platform .
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOP_DATA_DIR=/data \
    HOP_DOMAIN_PACKS_DIR=/app/domain_packs

WORKDIR /app

COPY requirements.lock ./
RUN pip install -r requirements.lock "psycopg[binary]>=3.2,<4"

COPY pyproject.toml README.md ./
COPY hop ./hop
COPY domain_packs ./domain_packs
COPY scripts ./scripts
RUN pip install --no-deps . \
    && useradd --create-home --uid 10001 hop \
    && mkdir -p /data \
    && chown -R hop:hop /data

USER hop
VOLUME ["/data"]
EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "--factory", "hop.api:create_app", "--host", "0.0.0.0", "--port", "8000"]
