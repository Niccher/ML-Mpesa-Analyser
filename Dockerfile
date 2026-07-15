FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl ca-certificates libgomp1 && rm -rf /var/lib/apt/lists/*

# ── Copy pre-built llama.cpp server binary + libs ────────
COPY llama-bin/llama-server /usr/local/bin/
COPY llama-bin/*.so* /usr/local/lib/
# Also copy to binary dir so ggml_backend_load_all() finds plugins
COPY llama-bin/*.so* /usr/local/bin/
RUN ldconfig && ldd /usr/local/bin/llama-server

# ── Copy Qwen2.5 1.5B-Instruct GGUF model ────────────────
COPY models/qwen2.5-1.5b-instruct-q4_k_m.gguf /models/

ENV MODEL_PATH=/models/qwen2.5-1.5b-instruct-q4_k_m.gguf
ENV LLAMA_PORT=8080
ENV GGML_BACKEND_PATH=/usr/local/bin

# ── Set up Python app ─────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080 9050
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
