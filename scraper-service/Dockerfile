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



# Copy pre-built packages from builder
COPY --from=builder /install /usr/local
# Create non-root user early so Playwright browsers can be installed
# into a writable path and chowned to the runtime user.
RUN useradd -m appuser

# Install Playwright browser binaries (chromium only, ~170 MB)

# Set an explicit browsers path inside the appuser home and install
# browsers there so the non-root `appuser` can access them at runtime.
ENV PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright
RUN python -m playwright install chromium \
 && chown -R appuser:appuser /home/appuser/.cache/ms-playwright


# Copy source
COPY . .

# Switch to the non-root user created earlier
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
