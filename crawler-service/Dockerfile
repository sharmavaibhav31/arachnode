FROM python:3.11-slim

# Install ALL Playwright/Chromium system dependencies manually.
# We do NOT use `playwright install --with-deps` because its internal apt-get
# references packages that no longer exist in Debian Trixie (python:3.11-slim):
#   ttf-unifont        → fonts-unifont
#   ttf-ubuntu-font-family → fonts-ubuntu
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget curl gnupg ca-certificates \
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
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

RUN useradd -m -u 1000 appuser

# Set Playwright path so it lands in appuser's home directory
ENV PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

RUN pip config set global.timeout 120 \
 && pip config set global.retries 5 \
 && pip install --upgrade pip

WORKDIR /app
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Install Chromium browser binary only with retries for network resilience
RUN for i in 1 2 3 4 5; do playwright install chromium && break || (echo "Retry $i..." && sleep 5); done \
 && chown -R appuser:appuser /home/appuser/.cache

USER appuser
COPY --chown=appuser:appuser . .

ENV SCRAPY_SETTINGS_MODULE=crawler.settings

EXPOSE 8004
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8004"]
