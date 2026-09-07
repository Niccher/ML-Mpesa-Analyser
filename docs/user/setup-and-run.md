# Setup and Run Guide — ML Mpesa Analyzer

This guide walks through starting and operating the **ML Mpesa Analyzer** container.

---

## 1. Prerequisites

- **Docker Engine** 24.0+ and **Docker Compose** v2
- At least **4 GB RAM** available on the host machine (model consumes ~1.5 GB in RAM)
- Network access to Hugging Face to download the GGUF model (~1.1 GB)

---

## 2. Step-by-Step Run Instructions

From the root of this repository:

### Step 1: Copy Environment Configuration
```bash
cp .env.example .env
```
Ensure that database settings in `.env` match your MySQL credentials if running outside the default `hosts-shared-network`.

### Step 2: Download the Quantized Model
Download the default Qwen2.5 1.5B Instruct model (Q4_K_M) into `models/`:
```bash
wget -P models/ https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

### Step 3: Start the Docker Container
```bash
docker compose up --build -d
```

### Step 4: Verify Health and Readiness
Watch container logs until llama-server loads the model and FastAPI binds to port 9050:
```bash
docker compose logs -f
```

Check the health endpoint:
```bash
curl -f http://localhost:9050/health
```

Expected response:
```json
{
  "status": "ok",
  "llm_provider": "openai-compatible",
  "llm_model": "qwen2.5-1.5b-instruct",
  "db_configured": true
}
```

### Step 5: Trigger a Test Processing Cycle
```bash
curl -X POST http://localhost:9050/process/trigger
```

### Step 6: Stopping the Service
```bash
docker compose down
```
To preserve database records, do not use the `-v` flag.
