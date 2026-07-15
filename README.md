# SMS Finance LLM Service

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)]()
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Docker-2496ED.svg)]()
[![Python](https://img.shields.io/badge/python-3.12-3776AB.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)]()
[![llama.cpp](https://img.shields.io/badge/llama.cpp-b10018-FF6F00.svg)]()
[![Model](https://img.shields.io/badge/model-Qwen2.5%201.5B%20Instruct-8A2BE2.svg)]()
[![Database](https://img.shields.io/badge/database-MySQL%208%2B-4479A1.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)]()

An autonomous microservice that reads unprocessed SMS messages from a MySQL database, classifies senders and extracts structured financial data using a local large language model (LLM), then writes the results back to the database — all without a hosted API dependency.

Built for the M-Pesa Analyzer ecosystem. Designed to run alongside a shared MySQL instance and a CodeIgniter 4 web frontend.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Docker Container                   │
│                                                      │
│  ┌─────────────────────┐   ┌──────────────────────┐  │
│  │   llama-server       │   │   FastAPI (uvicorn)   │  │
│  │   (llama.cpp)        │   │                      │  │
│  │   Port 8080          │   │   Port 9050           │  │
│  │   Qwen2.5 1.5B       │◄──│   /health             │  │
│  │   GGUF Q4_K_M        │   │   /process/trigger    │  │
│  └─────────────────────┘   │   /process/db          │  │
│          ▲                 └──────────┬───────────────┘  │
│          │                            │                  │
│          │              ┌─────────────▼─────────────┐   │
│          │              │   Background Poller        │   │
│          │              │   (every 30s)              │   │
│          │              │   Polls DB → LLM → Write   │   │
│          │              └───────────────────────────┘   │
│          │                                              │
└──────────┼──────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────┐
│  Shared MySQL DB     │
│  db_mpesa_analyzer   │
│                      │
│  tbl_Sms             │
│  tbl_Sender_Profiles │
│  tbl_Sms_Processing  │
│  tbl_Analyzed_       │
│    Transactions      │
└─────────────────────┘
```

### Data Flow

1. **Background Poller** runs every `POLL_INTERVAL` seconds, queries `tbl_Sms` for unprocessed messages (no `tbl_Sms_Processing` row, or existing row with `status = 'error'`).
2. **Sender Classification** — groups messages by sender (number), then classifies each sender via the LLM or a built-in known-sender lookup into categories: `Mobile Money`, `Bank`, `Fintech`, `SACCO`, `Insurance`, `Payments/Govt`, `Other Finance`, `Non-Finance`.
3. **Profile Upsert** — saves/updates the sender profile in `tbl_Sender_Profiles`.
4. **Transaction Extraction** — for finance senders, sends SMS bodies in batches to the LLM to extract structured fields: direction, amount, balance, counterparty, transaction type.
5. **DB Write** — updates `tbl_Sms` with extracted fields, inserts into `tbl_Analyzed_Transactions` for transactional messages, and records processing status.

---

## Technologies

| Layer | Technology | Role |
|-------|-----------|------|
| **LLM Inference** | [llama.cpp](https://github.com/ggerganov/llama.cpp) `b10018` | Local inference server for GGUF models. Runs as a subprocess inside the container, exposes an OpenAI-compatible HTTP API on port 8080. |
| **LLM Model** | [Qwen2.5 1.5B Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) (Q4_K_M) | 1.5-billion-parameter instruction-tuned model, quantized to 4-bit. Runs entirely on CPU. |
| **Web Framework** | [FastAPI](https://fastapi.tiangolo.com/) 0.115 | Async Python web framework serving the health endpoint and processing triggers. |
| **ASGI Server** | [Uvicorn](https://www.uvicorn.org/) 0.34 | Runs the FastAPI application. |
| **HTTP Client** | [httpx](https://www.python-httpx.org/) 0.28 | Async HTTP client for LLM API calls (OpenAI-compatible chat completions). |
| **Database** | [SQLAlchemy 2.0](https://www.sqlalchemy.org/) + [asyncmy](https://github.com/long2ice/asyncmy) 0.2 | Async MySQL driver and ORM-style connection management. |
| **Validation** | [Pydantic](https://docs.pydantic.dev/) 2.10 | Schema validation for LLM output and API request/response models. |
| **Container** | [Docker](https://www.docker.com/) | Single container bundling llama-server, Python app, and model. |
| **Database** | MySQL 8+ (shared, external) | Central database used by the web app and this service. |

---

## Project Structure

```
Mpesa Analyser Docker/
├── app/
│   ├── __init__.py
│   ├── config.py              # Environment-based settings
│   ├── main.py                # FastAPI app, poller, endpoints
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py      # Async SQLAlchemy engine
│   │   └── queries.py         # All SQL queries
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py         # Pydantic models & enums
│   ├── services/
│   │   ├── __init__.py
│   │   ├── classifier.py      # Sender classification logic
│   │   ├── extractor.py       # Batch extraction orchestration
│   │   └── llm_service.py     # OpenAI-compatible LLM client
│   └── utils/
│       ├── __init__.py
│       └── prompt_templates.py # LLM prompts & known-sender list
├── tests/
│   ├── __init__.py
│   ├── test_classifier.py
│   └── test_schemas.py
├── llama-bin/                  # Pre-built llama.cpp binaries
│   ├── llama-server
│   ├── libllama*.so*
│   ├── libggml*.so*
│   └── ...
├── models/
│   └── qwen2.5-1.5b-instruct-q4_k_m.gguf  # ~1.1 GB
├── .dockerignore
├── .env.example
├── .gitignore
├── Dockerfile
├── entrypoint.sh
├── docker-compose.yml
└── requirements.txt
```

---

## Setup

### Prerequisites

- Docker & Docker Compose v2
- A running MySQL 8+ instance (or use the shared one from the project's `docker-compose.yml`)
- ~2 GB free RAM (model loading + server overhead)
- ~1.1 GB free disk for the GGUF model

### Database Tables

The service expects these tables to exist. You can run the CI4 migration from the web app or apply the schema manually:

**`tbl_Sms`** — additional columns required:

| Column | Type | Purpose |
|--------|------|---------|
| `sms_direction` | VARCHAR(20) | `sent` / `received` / `none` |
| `sms_amount` | DECIMAL(15,2) | Transaction amount |
| `sms_balance` | DECIMAL(15,2) | Post-transaction balance |
| `sms_counterparty` | VARCHAR(255) | Other party in transaction |
| `sms_transaction_type` | VARCHAR(50) | `payment`, `transfer`, etc. |
| `sms_is_transactional` | TINYINT(1) | Whether the SMS is a financial transaction |

**`tbl_Sender_Profiles`** — sender classification cache:

| Column | Type | Purpose |
|--------|------|---------|
| `sp_id` | INT PK AUTO_INCREMENT | Primary key |
| `sp_owner` | VARCHAR(100) | SMS owner identifier |
| `sp_number` | VARCHAR(50) | Sender phone number |
| `sp_name` | VARCHAR(255) | Resolved sender name |
| `sp_category` | VARCHAR(100) | `Mobile Money`, `Bank`, etc. |
| `sp_is_finance` | TINYINT(1) | Finance flag |
| `sp_confidence` | DECIMAL(5,4) | Classification confidence |
| `sp_created` / `sp_updated` | DATETIME | Timestamps |

**`tbl_Sms_Processing`** — processing tracking:

| Column | Type | Purpose |
|--------|------|---------|
| `sms_id` | INT PK | FK to `tbl_Sms.id` |
| `status` | VARCHAR(20) | `pending` / `processing` / `done` / `error` / `skipped` |
| `attempt_count` | INT | Retry counter |
| `last_error` | TEXT | Last error message |
| `processed_at` | DATETIME | Completion timestamp |

**`tbl_Analyzed_Transactions`** — extracted transaction records (requires `orig_sms_int_id INT UNSIGNED` column added).

### Quick Start

1. **Clone or copy the repository.**

2. **Create a `.env` file** from the example:

   ```bash
   cp .env.example .env
   ```

   Edit the values to match your MySQL credentials and any custom settings.

3. **Place the GGUF model** in `models/`:

   ```bash
   # Download Qwen2.5 1.5B Instruct Q4_K_M
   wget -P models/ https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf
   ```

4. **Place the llama.cpp server binary** in `llama-bin/`:

   Download the pre-built binaries from the [llama.cpp releases](https://github.com/ggerganov/llama.cpp/releases) (Ubuntu x64, `llama-bXXXX-bin-ubuntu-x64.tar.gz`). Extract `llama-server` and all `.so` files into `llama-bin/`.

5. **Build and run:**

   ```bash
   docker compose up -d --build
   ```

   This starts the `sms-finance-llm` container with both the llama-server (port 8080) and the FastAPI app (port 9050).

6. **Verify:**

   ```bash
   curl http://localhost:9050/health
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

7. **Trigger processing:**

   ```bash
   curl -X POST http://localhost:9050/process/trigger
   ```

### Running Alongside the Full Stack

If you use the project-level `docker-compose.yml` (which includes MySQL, web app, and other services), add the service definition:

```yaml
sms-finance-llm:
  build: ./Mpesa Analyser Docker
  container_name: mpesa-analyser-docker
  ports:
    - "8080:8080"
    - "9050:9050"
  env_file:
    - ./Mpesa Analyser Docker/.env
  environment:
    - LLAMA_PORT=8080
    - LLM_BASE_URL=http://localhost:8080/v1
    - LLM_MODEL=qwen2.5-1.5b-instruct
    - LLM_PROVIDER=openai-compatible
  restart: unless-stopped
  depends_on:
    mysql:
      condition: service_healthy
  networks:
    - shared-network
```

---

## Configuration

All settings are driven by environment variables. See `.env.example`:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `openai-compatible` | LLM backend type |
| `LLM_API_KEY` | `not-needed` | API key (not needed for local llama.cpp) |
| `LLM_BASE_URL` | `http://localhost:8080/v1` | LLM API base URL |
| `LLM_MODEL` | `qwen2.5-1.5b-instruct` | Model name sent to LLM API |
| `LLM_MAX_TOKENS` | `2048` | Maximum tokens per LLM response |
| `DB_HOST` | `mysql` | MySQL host |
| `DB_PORT` | `3306` | MySQL port |
| `DB_USER` | `root` | MySQL user |
| `DB_PASSWORD` | *(empty)* | MySQL password |
| `DB_NAME` | `mpesa_analyzer` | MySQL database |
| `BATCH_SIZE` | `5` | Number of SMS per LLM extraction call |
| `MAX_RETRIES` | `3` | Max retries per message |
| `POLL_INTERVAL` | `30` | Background poller interval (seconds) |

---

## API Endpoints

### `GET /health`

Returns service health status.

**Response:**
```json
{
  "status": "ok",
  "llm_provider": "openai-compatible",
  "llm_model": "qwen2.5-1.5b-instruct",
  "db_configured": true
}
```

### `POST /process/trigger`

Manually trigger one processing cycle. Skips if another cycle is already running.

**Response:**
```json
{
  "senders_classified": 1,
  "messages_processed": 20,
  "finance_senders_found": 1,
  "transactional_inserted": 3,
  "errors": 0
}
```

Or, if already processing:
```json
{
  "status": "skipped",
  "reason": "already processing"
}
```

### `POST /process/db`

Alias for `/process/trigger`.

---

## How It Works

### Sender Classification (`classifier.py`)

1. Checks a built-in known-sender dictionary (`FINANCE_CATEGORIES` in `prompt_templates.py`) covering 60+ Kenyan financial senders across 7 categories.
2. If the sender is known, returns immediately with high confidence (0.95).
3. For unknown senders, calls the LLM with sample SMS messages for contextual classification.

### Transaction Extraction (`extractor.py`)

1. Sends SMS bodies in batches (`BATCH_SIZE` items) to the LLM.
2. The LLM returns a JSON array with per-message extractions.
3. Each extraction is validated against the `MessageExtraction` Pydantic schema.
4. Invalid or missing extractions are recorded as `None`.

### Background Poller (`main.py`)

1. Runs as an `asyncio.Task` started during the FastAPI lifespan.
2. Acquires an `asyncio.Lock` to prevent concurrent processing cycles.
3. Queries for unprocessed SMS (`status = 'error'` or no processing record).
4. Processes classification and extraction, then writes results to DB.
5. Sleeps for `POLL_INTERVAL` seconds between cycles.

### llama.cpp Server (`entrypoint.sh`)

1. Starts `llama-server` with the GGUF model, listening on port 8080.
2. Uses pre-built binaries from GitHub releases (avoids compiling from source).
3. Configures context size, batch size, CPU-only inference.
4. Health-check loop waits for the server to be ready before starting the Python app.

---

## Development

### Building Without Docker

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 9050
```

You will need a running llama.cpp server or any OpenAI-compatible endpoint.

### Adding a Known Sender

Edit `app/utils/prompt_templates.py` and add the sender to the appropriate category in `FINANCE_CATEGORIES`. The sender string is matched case-insensitively.

### Testing

```bash
python -m pytest tests/
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.115.6 | Web framework |
| `uvicorn` | 0.34.0 | ASGI server |
| `pydantic` | 2.10.4 | Data validation |
| `httpx` | 0.28.1 | Async HTTP client |
| `asyncmy` | 0.2.10 | Async MySQL driver |
| `sqlalchemy` | 2.0.36 | Database toolkit |
| `python-dotenv` | 1.0.1 | Environment loading |

---

## License

Private / Internal project — M-Pesa Analyzer ecosystem.
