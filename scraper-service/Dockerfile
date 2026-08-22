# ── Stage 1: Build dependencies ──────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN pip config set global.timeout 120 \
 && pip config set global.retries 5 \
 && pip install --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime with Playwright browsers ─────────────────────────────────
FROM python:3.11-slim

# Install ALL Playwright/Chromium system dependencies manually.
# We do NOT use `playwright install --with-deps` because its internal apt-get
# references packages that no longer exist in Debian Trixie (python:3.11-slim):
#   ttf-unifont        → fonts-unifont
#   ttf-ubuntu-font-family → fonts-ubuntu
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libasound2t64 \
        libpangocairo-1.0-0 \
        libgtk-3-0 \
        libx11-xcb1 \
        libxcb-dri3-0 \
        fonts-liberation \
        fonts-unifont \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pre-built packages from builder
COPY --from=builder /install /usr/local

# Create non-root user early so Playwright browsers land in appuser's home
RUN useradd -m appuser

ENV PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

# Install Chromium browser binary only (deps already installed above)
RUN python -m playwright install chromium \
 && chown -R appuser:appuser /home/appuser/.cache/ms-playwright

COPY . .

USER appuser

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
