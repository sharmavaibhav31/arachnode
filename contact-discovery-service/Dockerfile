# ── Stage 1: Runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim

# Playwright/Chromium system dependencies + curl (for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
        libgbm1 libasound2 libpangocairo-1.0-0 libgtk-3-0 \
        libx11-xcb1 libxcb-dri3-0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

ENV PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser binary as root but into appuser's path
RUN playwright install chromium --with-deps

# Give appuser ownership
RUN chown -R appuser:appuser /home/appuser/.cache

USER appuser

COPY --chown=appuser:appuser . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
