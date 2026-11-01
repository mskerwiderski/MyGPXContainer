FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock ./
# Dependencies exactly as locked in uv.lock: a rebuild never pulls a newer
# (possibly breaking) version, unlike an unpinned pip install.
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim
# Without MGC_AUTH the app runs in mode `single` and asks for its first
# account - it is never open (app/config.py). MGC_ROUTING_DIR: the volume
# shared with the routing container (routing/), used once MGC_ROUTING_URL is set.
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    MGC_DATA_DIR=/data MGC_ROUTING_DIR=/routing
# rasterio's wheel (the elevation tiles, app/dem/) needs the system's expat;
# python:3.12-slim does not have it (found live 2026-11-01: "libexpat.so.1")
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/venv /opt/venv
RUN useradd -u 1000 -m app && mkdir -p /data /routing && chown app:app /data /routing
WORKDIR /app
COPY --chown=app:app app /app/app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
