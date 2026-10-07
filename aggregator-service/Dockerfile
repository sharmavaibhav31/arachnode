# ── Stage 1: build ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN pip config set global.timeout 120 \
 && pip config set global.retries 5 \
 && pip install --upgrade pip

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu --prefix=/install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim

# Install curl for Docker healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pre-built site-packages from builder stage
COPY --from=builder /install /usr/local

# Non-root user for security
RUN useradd -m appuser

# Set Hugging Face cache dir to appuser home
ENV HF_HOME=/home/appuser/.cache/huggingface

# Pre-download SentenceTransformer model during build so it never downloads at runtime
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" \
 && chown -R appuser:appuser /home/appuser/.cache

# Copy application source
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
