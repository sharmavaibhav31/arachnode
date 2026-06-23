FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    fonts-liberation libappindicator3-1 xdg-utils \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

# Set Playwright path so it lands in appuser's home directory
ENV PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir fastapi uvicorn pydantic

RUN playwright install chromium
RUN chown -R appuser:appuser /home/appuser/.cache

USER appuser
COPY --chown=appuser:appuser . .

ENV SCRAPY_SETTINGS_MODULE=crawler.settings

EXPOSE 8004
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8004"]
