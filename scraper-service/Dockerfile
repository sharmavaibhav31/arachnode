# ── Stage 1: Build dependencies ──────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime with Playwright browsers ─────────────────────────────────
FROM python:3.11-slim

# System packages required by Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
        libgbm1 libasound2 libpangocairo-1.0-0 libgtk-3-0 \
        libx11-xcb1 libxcb-dri3-0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Keep browser binaries in a shared location accessible to the runtime user.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Copy pre-built packages from builder
COPY --from=builder /install /usr/local

# Install Playwright browser binaries (chromium only, ~170 MB)
RUN mkdir -p /ms-playwright && playwright install chromium

# Copy source
COPY . .

# Non-root user
RUN useradd -m appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
