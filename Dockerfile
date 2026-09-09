# syntax=docker/dockerfile:1
FROM python:3.12-slim

# ── OS deps ───────────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        libgomp1 \
        procps \
    && rm -rf /var/lib/apt/lists/*

# ── 1. Python dependencies — installed FIRST before any heavy files ───────────
# This is the most important cache layer: pip install only re-runs when
# requirements.txt changes, NOT when app code or the model file changes.
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── 2. llama.cpp server binary + shared libs ──────────────────────────────────
COPY llama-bin/llama-server /usr/local/bin/
COPY llama-bin/*.so* /usr/local/lib/
COPY llama-bin/*.so* /usr/local/bin/
RUN ldconfig && ldd /usr/local/bin/llama-server

# ── 3. Large GGUF model ───────────────────────────────────────────────────────
RUN mkdir -p /models && \
    curl -L --retry 3 -o /models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
    https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf

# ── 4. Application code ────────────────────────────────────────────────────────
COPY app/ ./app/

ENV MODEL_PATH=/models/qwen2.5-1.5b-instruct-q4_k_m.gguf
ENV LLAMA_PORT=8080
ENV GGML_BACKEND_PATH=/usr/local/bin

# ── Entrypoint ────────────────────────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080 9050

# --reload kept intentionally for instant code updates during development
CMD ["/entrypoint.sh"]
