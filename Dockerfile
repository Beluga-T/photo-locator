# syntax=docker/dockerfile:1

# ── Build stage ──────────────────────────────────────────────────────
# Wheels are resolved here so the runtime image carries no pip cache and
# no build toolchain. Pillow ships manylinux wheels for every format this
# app accepts, so no system image libraries are needed in either stage.
FROM python:3.12-slim AS build

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


# ── Runtime stage ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Unbuffered so uvicorn's log lines reach `docker logs` as they happen;
# no .pyc because the filesystem is mounted read-only at runtime.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    RIL_DATA_DIR=/data

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY app/ ./app/
COPY web/ ./web/

# Nothing in this image is ever written to. The application holds uploads
# in memory only, and compose additionally mounts the root filesystem
# read-only — running as a non-root user makes that boundary meaningful.
RUN useradd --system --create-home --uid 10001 locator

# The one writable path in the image. compose mounts a volume over it, but the
# directory has to exist and be owned by the runtime user first — otherwise the
# read-only root makes the very first write fail.
RUN mkdir -p /data && chown locator:locator /data
VOLUME ["/data"]

USER locator

EXPOSE 8000

# No curl in slim, and adding it just for this would widen the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"]

# --host 0.0.0.0 is required *inside* the container — the port is only
# reachable from outside through whatever the host publishes, and
# compose.yaml deliberately publishes to 127.0.0.1 only. Binding to
# localhost here would make the container unreachable, not safer.
#
# --no-proxy-headers is not optional: uvicorn otherwise rewrites the
# client address from X-Forwarded-For before the app sees it, which
# lets a caller forge a fresh rate-limit bucket per request. Drop it
# only when a proxy you control sits in front, and then also set
# TRUSTED_PROXIES to that proxy's address.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--no-proxy-headers", \
     "--no-server-header", \
     "--log-level", "info"]
