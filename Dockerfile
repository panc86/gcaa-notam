# ---- Stage 1: build wheel ----
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir build \
    && python -m build --wheel --outdir /build/dist

# ---- Stage 2: runtime ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NOTAM_DATA_DIR=/app/data

# Install the wheel first (no native deps needed)
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Install only the headless shell variant of Chromium and its OS deps.
# --only-shell skips the full Chromium browser (~350 MB saved).
RUN playwright install --with-deps --only-shell chromium \
    && rm -rf /root/.cache/ms-playwright/ffmpeg-* /var/lib/apt/lists/*

WORKDIR /app

# Data volume for downloads, output, and logs
VOLUME /app/data

CMD ["notam"]
