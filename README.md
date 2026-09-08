# SMS Finance LLM Service

Autonomous financial transaction processor powered by a local large language model (LLM). Reads unprocessed M-Pesa SMS from MySQL, classifies senders, extracts structured amounts and counterparties, and writes results back.

Stack: Python 3.12, FastAPI, llama.cpp, Qwen2.5 1.5B (GGUF), MySQL 8.4

**If you only need to run the service, this page is enough.**  
Software engineers: [docs/README.md](docs/README.md).

---

## What “Running” Looks Like

| Component | URL / Port | Expected Response / Check |
|-----------|------------|---------------------------|
| **FastAPI Service** | http://localhost:9050 | API active |
| **Health Check** | http://localhost:9050/health | `{"status": "ok", "llm_model": "qwen2.5-1.5b-instruct"}` |
| **OpenAPI Docs** | http://localhost:9050/docs | Interactive Swagger UI |
| **llama-server** | http://localhost:8080/health | HTTP 200 (Model loaded in memory) |

---

## Prerequisites

### Option A — Docker (Recommended)
- Git
- Docker Engine 24+ & Docker Compose v2
- Minimum 4 GB host RAM

### Option B — Without Docker
- Python 3.12+
- llama-server binary in `llama-bin/`
- Running MySQL 8.4 instance
- Native run details: [docs/engineering/local-development.md](docs/engineering/local-development.md)

---

## Setup and Run

1. Clone the repository and navigate to folder:
   ```bash
   cd "ML Mpesa Analyzer"
   ```
2. Copy environment template:
   ```bash
   cp .env.example .env
   ```
3. Download the quantized Qwen2.5 1.5B model weights into `models/`:
   ```bash
   wget -P models/ https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf
   ```
4. Start the container stack:
   ```bash
   docker compose up --build -d
   ```
5. Confirm service health:
   ```bash
   curl http://localhost:9050/health
   ```
6. Stop the service:
   ```bash
   docker compose down
   ```

---

## Configuration Users May Change

| Variable | Default | Purpose |
|----------|---------|---------|
| `DB_HOST` | `mysql` | MySQL hostname |
| `DB_NAME` | `db_mpesa_analyzer` | Database schema name |
| `MODEL_PATH` | `/models/qwen2.5-1.5b-instruct-q4_k_m.gguf` | Active GGUF model path |
| `BATCH_SIZE` | `20` | Messages evaluated per LLM extraction call |
| `POLL_INTERVAL` | `30` | Seconds between background DB poll queries |

Full parameter reference: [docs/user/configuration.md](docs/user/configuration.md).

---

## Deployment (Railway & Cloud)

### Quick Setup Steps on Railway
1. Create a new project on Railway and attach a **MySQL** database plugin.
2. Deploy the **ML Microservice** container repository connected to the MySQL service.
3. Deploy the **WebApp** repository connected to the same MySQL service.
4. Copy-paste the environment variables below into Railway's **Variables -> Bulk Raw Editor**.

### Python ML Microservice Environment Variables

**JSON Bulk Import Format:**
```json
{
  "MYSQL_HOST": "${{MySQL.MYSQLHOST}}",
  "MYSQL_USER": "${{MySQL.MYSQLUSER}}",
  "MYSQL_PASSWORD": "${{MySQL.MYSQLPASSWORD}}",
  "MYSQL_DATABASE": "${{MySQL.MYSQLDATABASE}}",
  "MYSQL_PORT": "${{MySQL.MYSQLPORT}}",
  "PORT": "9050",
  "GEMINI_API_KEY": "<YOUR_GEMINI_API_KEY>"
}
```

**Raw `.env` Format:**
```env
MYSQL_HOST=${{MySQL.MYSQLHOST}}
MYSQL_USER=${{MySQL.MYSQLUSER}}
MYSQL_PASSWORD=${{MySQL.MYSQLPASSWORD}}
MYSQL_DATABASE=${{MySQL.MYSQLDATABASE}}
MYSQL_PORT=${{MySQL.MYSQLPORT}}
PORT=9050
GEMINI_API_KEY=<YOUR_GEMINI_API_KEY>
```

### Health & Database Probe
- **Microservice Liveness & DB Connection Probe**: `GET https://<your-ml-domain>.up.railway.app/health`
  *Returns `{"status": "ok", "db_configured": true}` when Python microservice successfully queries the MySQL container.*

---

## Something Went Wrong?

- **Container fails health check**: Model file may be missing from `models/`. Check `ls -lh models/`.
- **Address already in use on port 9050/8080**: Set `ML_MPESA_ANALYZER_API_PORT` in `.env`.
- **Database connection error**: Verify MySQL is healthy on `hosts-shared-network`.
- Full operational guide: [docs/user/troubleshooting.md](docs/user/troubleshooting.md).

---

## Software Engineers

- **Architecture Overview**: [docs/architecture/overview.md](docs/architecture/overview.md)
- **Inter-Service Communication**: [docs/architecture/communication.md](docs/architecture/communication.md)
- **Data & Canonical Storage**: [docs/architecture/data-and-storage.md](docs/architecture/data-and-storage.md)
- **FastAPI Service Handbook**: [docs/services/fastapi.md](docs/services/fastapi.md)
- **LLM Inference & Prompts**: [docs/services/ml.md](docs/services/ml.md)
- **Making Changes & Testing**: [docs/engineering/making-changes.md](docs/engineering/making-changes.md)
