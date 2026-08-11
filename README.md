# SMS Finance LLM Service

**Autonomous DB-to-DB SMS financial processor using a local large language model (LLM).** Reads unprocessed SMS from a shared MySQL database, classifies senders, extracts structured financial data, and writes the results back — all without a hosted API dependency.

[![Python](https://img.shields.io/badge/python-3.12-3776AB.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)]()
[![llama.cpp](https://img.shields.io/badge/llama.cpp-b10018-FF6F00.svg)]()
[![Model](https://img.shields.io/badge/model-Qwen2.5%201.5B-8A2BE2.svg)]()
[![Database](https://img.shields.io/badge/database-MySQL%208%2B-4479A1.svg)]()
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## The Three-Repos Ecosystem

This service is the **intelligence layer** of the M-Pesa Analyzer stack. The three repositories work together:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    M-Pesa Analyzer Ecosystem                         │
│                                                                      │
│  ┌──────────────────────┐    ┌──────────────────────┐               │
│  │  Android App          │    │  CI4 Web Backend     │               │
│  │  (Mpesa_Analyzer_App) │    │  (Mpesa Analyzer     │               │
│  │                       │    │   WebApp)            │               │
│  │  Reads MPESA SMS      │    │                      │               │
│  │  Encrypts & uploads   │───▶│  Decrypts payload    │──┐            │
│  │  to backend           │    │  Stores in MySQL     │  │            │
│  │                       │    │  Serves dashboard    │  │            │
│  │  [Kotlin / Retrofit]  │    │  [PHP / CI4 / Shield] │  │            │
│  └──────────────────────┘    └──────────────────────┘  │            │
│                                                         │            │
│                                                         ▼            │
│                                              ┌──────────────────────┐│
│                                              │  Docker LLM Service   ││
│                                              │  (Mpesa Analyser      ││
│                                              │   Docker)             ││
│                                              │                       ││
│                                              │  Polls DB for         ││
│                                              │  unprocessed SMS      ││
│                                              │  Classifies senders   ││
│                                              │  Extracts transactions││
│                                              │  Writes back to DB    ││
│                                              │                       ││
│                                              │  [Python / FastAPI /  ││
│                                              │   llama.cpp / Qwen2.5]││
│                                              └──────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
```

### How they depend on each other

| Step | Android App | Web Backend | Docker LLM |
|------|------------|-------------|------------|
| **1. Capture** | Reads SMS from device, encrypts with AES-128-CBC | — | — |
| **2. Upload** | Sends encrypted file via `POST /process/upload` | Decrypts, parses JSON, stores SMS in `tbl_Sms` | — |
| **3. Process** | — | Inserts job in `tbl_Processing_Jobs`, calls `POST /process/for-user/{id}` | Polls `tbl_Sms` (or triggered by web), classifies senders & extracts amounts |
| **4. Enrich** | — | — | Updates `tbl_Sms` (single canonical record) with classification + parsed data, upserts `tbl_Sender_Profiles`; `tbl_Sms_Classification` and `tbl_Analyzed_Transactions` are now **views** over `tbl_Sms` |
| **5. Visualise** | Fetches summaries via `get/my_uploads`, `get/my_summary_calculations` | Dashboard shows classified transactions, budgets, reports | — |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Docker Container                              │
│                                                                   │
│  ┌────────────────────────┐       ┌─────────────────────────────┐│
│  │  llama-server            │       │  FastAPI (uvicorn)          ││
│  │  (llama.cpp b10018)      │       │  Port 9050                  ││
│  │  Port 8080               │       │                             ││
│  │  Qwen2.5 1.5B Q4_K_M    │◄──────│  /health                    ││
│  │  GGUF model             │       │  /process/trigger           ││
│  └────────────────────────┘       │  /process/for-user/{id}     ││
│            ▲                       │  /admin/* (management)      ││
│            │                       └──────────┬──────────────────┘│
│            │              ┌────────────────────▼─────────────┐    │
│            │              │  Background Poller (POLL_INTERVAL)│   │
│            │              │  Gate: admin auto-jobs toggle     │   │
│            │              │                                  │    │
│            │              │  1. Query unprocessed SMS         │    │
│            │              │  2. Group by sender number        │    │
│            │              │  3. Classify sender (known-dict   │    │
│            │              │     or LLM, DB prompt override)   │    │
│            │              │  4. Upsert sender profile         │    │
│            │              │  5. Extract transactions (LLM)    │    │
│            │              │  6. Write one canonical row/tbl_Sms│   │
│            │              └──────────────────────────────────┘    │
│            │                                                      │
└────────────┼──────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│                  Shared MySQL 8.4 Database                    │
│                  db_mpesa_analyzer                            │
│                                                               │
│  tbl_Sms (CANONICAL) ── classification columns                │
│    sms_category, sms_is_finance, sms_confidence, sms_method   │
│    + parsed: sms_direction, sms_amount, sms_balance,          │
│      sms_counterparty, sms_transaction_type,                  │
│      sms_is_transactional, sms_trans_id, sms_trans_date       │
│                                                               │
│  tbl_Sender_Profiles ── sp_number, sp_name, sp_category,      │
│                         sp_is_finance, sp_confidence           │
│                                                               │
│  tbl_Sms_Processing ── sms_id, status, attempt_count, errors  │
│                                                               │
│  VIEW tbl_Sms_Classification ── derived from tbl_Sms          │
│  VIEW tbl_Analyzed_Transactions ── derived from tbl_Sms       │
│                                                               │
│  tbl_Processing_Jobs ── job runs + metadata (JSON)            │
│  tbl_LLM_Prompts ── versioned prompt overrides                │
│  tbl_ML_Controls ── admin toggles (auto_jobs_enabled)         │
└─────────────────────────────────────────────────────────────┘
```

---

## Classification Pipeline (Step by Step)

### Step 1: Polling
The background poller runs every `POLL_INTERVAL` (default 30s). It only runs while the admin **auto-jobs toggle** is enabled (`tbl_ML_Controls.auto_jobs_enabled`). It queries `tbl_Sms` for rows with no `tbl_Sms_Processing` record, or with `status = 'error'`. Batches are fetched in configurable sizes (`BATCH_SIZE`, default 5).

### Step 2: Sender Classification
Messages are grouped by sender phone number. For each sender:

1. **Known-sender lookup** — checks the allowed-sender list, loaded **DB-first from `tbl_Allowed_Senders`**, falling back to a built-in curated dictionary (`FINANCE_CATEGORIES` in `prompt_templates.py`) covering 60+ Kenyan financial senders across 7 categories:
   - **Mobile Money**: MPESA, Airtel Money, T-Kash, Telkom
   - **Bank**: KCB, Equity, NCBA, Co-op, Absa, StanChart, I&M, Stanbic, DTB, Sidian, Family Bank, Credit Bank, BOA, EcoBank, UBA, and more
   - **Fintech**: M-Shwari, Tala, Branch, Zenka, Timiza, Hustler Fund, OKash, KCB M-PESA
   - **SACCO**: Stima SACCO, Mwalimu SACCO, Unaitas, Harambee, Kenya Police, Afya, Safaricom
   - **Insurance**: Britam, Jubilee, CIC, APA, UAP Old Mutual, Madison
   - **Payments/Govt**: PesaLink, KRA, eCitizen
   
   If found: returns classification with 0.95 confidence immediately — **zero LLM calls** for known senders.

2. **LLM classification** — for unknown senders, sends up to 10 sample SMS messages to the LLM asking for: `is_finance`, `category`, `confidence`, `reasoning`.

The prompt used is resolved by `prompt_manager`: an **active DB prompt** in `tbl_LLM_Prompts` (per key `classify_sender`) takes precedence, otherwise the **hardcoded default** template is used. Admins can version prompts via the admin API — edits always create a new version.

### Step 3: Profile Persistence
Each sender's classification is upserted into `tbl_Sender_Profiles`. This creates a persistent cache — once a sender is classified, subsequent encounters skip the LLM and use the stored profile.

### Step 4: Single Canonical Write
Every SMS is written **once** to `tbl_Sms` via `upsert_sms_analysis()` — a single row carrying both the classification (`sms_category`, `sms_is_finance`, `sms_confidence`, `sms_method`, `sms_direction`) and, for finance senders, the parsed fields (`sms_amount`, `sms_balance`, `sms_counterparty`, `sms_transaction_type`, `sms_is_transactional`, `sms_trans_id`, `sms_trans_date`).

`tbl_Sms_Classification` and `tbl_Analyzed_Transactions` are **MySQL VIEWs** derived from `tbl_Sms` — they are never written to directly, so there is exactly one source of truth per SMS.

### Step 5: Transaction Extraction
For SMS from finance-category senders, messages are batched (default 5 per call) and sent to the LLM for structured extraction:

```
Input:  SMS body text
Output: {
  "is_transactional": true/false,
  "amount_before": 1000.00,
  "amount_after": 850.00,
  "amount_changed": 150.00,
  "direction": "sent"|"received"|"none",
  "counterparty": "John Doe",
  "transaction_type": "transfer"|"payment"|"deposit"|...
  "transaction_reference": "ABC123",
  "transaction_time": "9/7/26 at 6:14 am"
}
```

The extraction prompt (`extract_batch`) is likewise resolved from the active DB prompt or the hardcoded default.

### Step 6: Job Recording & Metadata
- Non-finance senders' SMS are marked `skipped` and are not extracted.
- Finance senders' SMS are extracted; transactional ones increment the job's `transactional_inserted` count; each is marked `done` (or `error`).
- Every user-triggered job (`/process/for-user/{id}`) records rich metadata in `tbl_Processing_Jobs.metadata` (JSON): sender/SMS breakdowns (total / finance / unwanted / skipped), category counts, direction counts, model + model path, LLM tuning (tokens, temperature, context, batch, GPU layers), batch/retries/poll settings, duration, and errors. The webapp surfaces this in the user-facing ML Jobs report.

---

## Model in Use

**Current model:** [Qwen2.5 1.5B Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) (Q4_K_M quantization)

| Property | Value |
|----------|-------|
| **Architecture** | Transformer with 1.5B parameters |
| **Quantization** | Q4_K_M (4-bit, ~1.1 GB file) |
| **Context length** | 16,384 tokens (configured via `--ctx-size`) |
| **Instruction-tuned** | Yes — responds to structured prompts reliably |
| **Output format** | JSON via `response_format: json_object` |
| **Inference** | 100% CPU (no GPU needed) |
| **Speed** | ~10-20 tokens/second on modern x86 CPU |

### Why Qwen2.5 1.5B?

- Small enough to run comfortably on CPU with only ~2 GB RAM overhead
- Large context window (16K) handles batch extraction of multiple SMS
- Excellent JSON adherence with instruction-tuned variant
- Quantized to 4-bit with minimal accuracy loss for classification tasks
- Widely available on Hugging Face in GGUF format

### Other Models That Can Be Used

The service is model-agnostic via the OpenAI-compatible API. Any GGUF model loaded by `llama-server` will work. Good alternatives:

| Model | Parameters | Quantization | Size | Trade-off |
|-------|-----------|-------------|------|-----------|
| **Llama 3.2 3B Instruct** | 3B | Q4_K_M | ~2.0 GB | Higher accuracy but more RAM |
| **Phi-3 Mini 3.8B** | 3.8B | Q4_K_M | ~2.5 GB | Strong at structured extraction |
| **Mistral 7B** | 7B | Q2_K | ~2.7 GB | Better understanding, larger model |
| **Gemma 2 2B** | 2B | Q4_K_M | ~1.3 GB | Good balance, slightly larger |
| **Llama 3.2 1B Instruct** | 1B | Q4_K_M | ~0.8 GB | Faster, slightly less accurate |
| **Qwen2.5 0.5B Instruct** | 0.5B | Q4_K_M | ~0.4 GB | Fastest, lowest accuracy |

**To swap models:**
1. Download a different GGUF file into `models/` (mounted into the container at `/models/`)
2. Either activate it through the admin UI / `POST /admin/models/activate`, or update `MODEL_PATH` in `docker-compose.yml` / `.env`
3. Update `LLM_MODEL` to match the model name
4. Rebuild / restart: `docker compose up -d --build`

Models can also be **uploaded** through the admin API (`POST /admin/models/upload`, multipart `.gguf`/`.bin`) and deleted (`POST /admin/models/delete`). GGUF metadata (parameter count, quantization, context length, architecture) is read automatically from the file header and surfaced via the admin status/model endpoints.

The `LLM_PROVIDER` can also be switched to any OpenAI-compatible API (`openai/gpt-4o-mini`, `anthropic/claude-3-haiku`, `groq/llama-3.1-8b`, etc.) by changing `LLM_BASE_URL` and `LLM_API_KEY` — no code changes required.

---

## Container Setup

### Structure

The Docker container bundles three processes in one image:

```
Dockerfile
├── Base: python:3.12-slim
├── System: curl, ca-certificates, libgomp1 (OpenMP)
├── llama.cpp: pre-built llama-server binary + shared libs (.so)
├── GGUF model: Qwen2.5 1.5B in /models/
├── Python app: FastAPI + uvicorn in /app/
└── Entrypoint: entrypoint.sh
```

### Entrypoint Flow (`entrypoint.sh`)

1. **Start llama-server** as background process:
   ```
   llama-server --model ${MODEL_PATH} \
                --port 8080 --host 0.0.0.0 \
                --ctx-size ${LLM_CTX_SIZE} \
                --batch-size ${LLM_BATCH_SIZE} \
                --n-gpu-layers ${N_GPU_LAYERS} \
                --mlock
   ```
   - `--mlock` pins model in RAM (prevents swapping)
   - `--n-gpu-layers 0` forces CPU-only inference
   - `--ctx-size 16384` supports large batch prompts
   - Context / batch / GPU layers are **env-driven**, so config changes apply on restart

2. **Health-check loop** — polls `http://localhost:8080/health` up to 60 times (2s intervals) until llama-server responds

3. **Start FastAPI** via `uvicorn app.main:app --host 0.0.0.0 --port 9050` (replaces shell with `exec`)

### Ports

| Port | Service | Purpose |
|------|---------|---------|
| 8080 | llama-server | OpenAI-compatible chat completions API |
| 9050 | FastAPI | Health, processing, and admin management endpoints |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `openai-compatible` | LLM backend (swap to any OpenAI API) |
| `LLM_BASE_URL` | `http://localhost:8080/v1` | LLM API endpoint |
| `LLM_MODEL` | `qwen2.5-1.5b-instruct` | Model name sent to LLM |
| `LLM_MAX_TOKENS` | `2048` | Max response tokens |
| `LLM_TEMPERATURE` | `0.2` | Sampling temperature for the LLM |
| `LLM_CTX_SIZE` | `16384` | llama.cpp context window (applied on restart) |
| `LLM_BATCH_SIZE` | `512` | llama.cpp prompt-processing batch (applied on restart) |
| `N_GPU_LAYERS` | `0` | Layers offloaded to GPU, 0 = CPU only (applied on restart) |
| `DB_HOST` | `mysql` | MySQL server hostname |
| `DB_PORT` | `3306` | MySQL port |
| `DB_USER` | `root` | MySQL user |
| `DB_PASSWORD` | *(empty)* | MySQL password |
| `DB_NAME` | `mpesa_analyzer` | Database name |
| `BATCH_SIZE` | `5` | SMS per LLM extraction call |
| `POLL_INTERVAL` | `30` | Background poll interval (seconds) |
| `MAX_RETRIES` | `3` | Max retries per message |
| `MODEL_PATH` | `/models/qwen2.5-1.5b-instruct-q4_k_m.gguf` | Active model file loaded by llama-server |
| `MODEL_DIR` | `/models` | Directory scanned for available model files |

---

## Why Machine Learning vs Hardcoded Scanners?

Traditional SMS parsing relies on **hardcoded regex patterns** — hand-written rules that match known SMS formats. The M-Pesa Analyzer Android app uses this approach for initial parsing. However, the Docker LLM service goes far beyond what regex can achieve:

### Limitations of hardcoded regex scanners

| Limitation | Example |
|------------|---------|
| **Brittle against format changes** | When Safaricom updates their SMS template, every regex breaks and must be manually updated |
| **Cannot handle unknown senders** | A new bank, fintech, or payment provider requires new rules |
| **No sender name resolution** | Regex can't determine that "254712345678" is "KCB Bank" |
| **No contextual understanding** | "Sent 500 to John" vs "Received 500 from John" — direction depends on context |
| **No partial confidence** | Regex returns match/no-match — no concept of "80% likely a transfer" |
| **High maintenance** | Each new SMS format = code change + app update + play store review |

### Advantages of LLM-based classification

| Advantage | How the LLM delivers |
|-----------|---------------------|
| **Format-agnostic** | The LLM understands natural language — it doesn't care about exact wording or template layout |
| **Zero-shot classification** | A new sender with a completely unknown format is classified correctly based on SMS content alone |
| **Sender resolution** | The LLM identifies "KCB MPESA" from "SM: KCBMPESA" — no lookup table needed |
| **Contextual direction** | Understands "You have received" vs "You have sent" even when wording is unconventional |
| **Confidence scoring** | Returns 0.0–1.0 confidence, allowing downstream logic to handle low-confidence cases |
| **Adaptive without code changes** | Senders self-classify over time — no app updates needed |
| **Multi-language** | Can handle Sheng, code-switching (English + Swahili), and informal abbreviations |
| **Extracts partial data** | If an SMS has an amount but no date, the LLM extracts what's available and returns null for the rest |
| **Schema-validated output** | Pydantic validates every LLM response — malformed JSON is caught and retried |

### Concrete example

```
SMS: "KSH500.00 sent to JOHN DOE. New M-PESA balance is KSH2,450.00.
      Transaction cost, KSH0.00. To reverse, dial *456#. 
      You are now on Fuliza. Limit KSH1,000.00"

Regex approach:  Needs a specific pattern for Safaricom's "sent to" format.
                 What if they add a new line? Break.
                 What about "Fuliza limit KSH1,000"? Regex wouldn't extract it
                 as a separate financial event.

LLM approach:    Extracts: amount_changed=500, direction="sent", 
                 counterparty="JOHN DOE", balance_after=2450,
                 and separately identifies "Fuliza limit=1000" 
                 — all in one call, without any format-specific rules.
```

---

## API Endpoints

### `GET /health`
Returns service health:
```json
{"status": "ok", "llm_provider": "openai-compatible", "llm_model": "qwen2.5-1.5b-instruct", "db_configured": true}
```

### `POST /process/trigger`
Manually trigger one processing cycle (blocked when auto jobs are disabled):
```json
{"senders_classified": 1, "messages_processed": 20, "finance_senders_found": 1, "transactional_inserted": 3, "errors": 0}
```

### `POST /process/for-user/{user_id}`
Process unprocessed SMS for a specific user (called by CI4 web backend):
```json
{"job_id": 42, "user_id": "abc123", "status": "done", "messages_processed": 15, "errors": 0, "duration_seconds": 12}
```

### `POST /process/db`
Alias for `/process/trigger` — one processing cycle.

### Admin endpoints (`/admin/*`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/admin/status` | GET | Full backend status: health, config, model files + GGUF metadata, DB, uptime, `auto_jobs_enabled` |
| `/admin/models` | GET | List available model files with GGUF metadata + active model path |
| `/admin/models/upload` | POST | Upload a `.gguf`/`.bin` model (multipart `file`), streamed in 1 MB chunks |
| `/admin/models/activate` | POST | Mark a model active (updates `MODEL_PATH`/`LLM_MODEL`); restart required |
| `/admin/models/delete` | POST | Delete a model file (active and non-GGUF files are refused) |
| `/admin/config` | POST | Update in-memory config + `.env` (model, tokens, temperature, ctx, batch, GPU layers, batch size, retries, poll) |
| `/admin/test-prompt` | POST | Run a classification + extraction on sample messages to verify the LLM |
| `/admin/prompts` | GET | List prompt versions + per-key resolution (DB active vs hardcoded default) |
| `/admin/prompts` | POST | Create a new prompt version (edit = new version, set active) |
| `/admin/prompts/{id}/activate` | POST | Activate an existing prompt version |
| `/admin/prompts/{id}/delete` | POST | Delete a prompt version (active versions blocked) |
| `/admin/jobs/status` | GET | Auto-jobs toggle state + aggregate totals from recent jobs |
| `/admin/jobs/auto` | POST | `{"enabled": bool}` — start/stop the background poller |
| `/admin/jobs` | GET | Recent processing jobs with full metadata |
| `/admin/allowed/defaults` | GET | The hardcoded default finance senders (fallback allowlist) |

**Auto-jobs control:** when `POST /admin/jobs/auto {"enabled": false}`, the background poller goes idle and `/process/trigger`, `/process/db` and `/process/for-user/{id}` are all blocked (the latter records a job with `status: disabled`). The toggle is persisted in `tbl_ML_Controls` so it survives restarts.

---

## Quick Start

```bash
cp .env.example .env
# Edit .env with your MySQL credentials

# Place model in models/
wget -P models/ https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf

# Place llama-server binary in llama-bin/ (from GitHub releases)

docker compose up -d --build

# Verify
curl http://localhost:9050/health

# Trigger processing
curl -X POST http://localhost:9050/process/trigger
```

For the full stack (MySQL + Web + LLM), add the service to the project-level `docker-compose.yml` that includes MySQL and the CI4 web app.

---

## Project Structure

```
├── app/
│   ├── main.py                    # FastAPI app, poller, processing pipeline, API endpoints
│   ├── config.py                  # Environment-driven settings (LLM tuning, DB, processing)
│   ├── db/
│   │   ├── connection.py          # Async SQLAlchemy engine
│   │   └── queries.py             # All SQL operations (canonical writes, prompts, jobs, controls)
│   ├── models/
│   │   └── schemas.py             # Pydantic models & enums
│   ├── routers/
│   │   └── admin.py               # Admin management API (models, config, prompts, jobs, toggle)
│   ├── services/
│   │   ├── classifier.py          # Sender classification (known-dict + LLM)
│   │   ├── extractor.py           # Batch transaction extraction
│   │   ├── llm_service.py         # OpenAI-compatible LLM client
│   │   ├── prompt_manager.py      # Prompt resolution (DB override → hardcoded default)
│   │   └── gguf_metadata.py       # GGUF model header metadata reader
│   └── utils/
│       └── prompt_templates.py    # Default prompts + 60+ known sender dictionary
├── llama-bin/                     # Pre-built llama.cpp binaries
├── models/                        # GGUF model files
├── tests/                         # Pytest tests
├── Dockerfile                     # Container build
├── entrypoint.sh                  # Startup script (llama-server + health wait + uvicorn)
├── docker-compose.yml             # Standalone deployment
└── requirements.txt               # Python dependencies
```

---

## Development

### Testing

```bash
python -m pytest tests/
```

### Adding a Known Sender

Two ways:

1. **Via the DB allowlist (recommended)** — insert a row into `tbl_Allowed_Senders` (`sender`, `category`). The backend reads this first and falls back to the hardcoded list only when it's empty. The webapp's admin *Allowed Senders* page manages this table.
2. **Hardcoded fallback** — edit `app/utils/prompt_templates.py`, adding the sender name (uppercase) to the appropriate category in `FINANCE_CATEGORIES`. Match is case-insensitive. These defaults are also exposed via `GET /admin/allowed/defaults` so the webapp can show them even before the user has matching data.

### Running Without Docker

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 9050
```

Requires a running llama.cpp server (or any OpenAI-compatible endpoint).

---

## License

MIT License — see the [LICENSE](LICENSE) file in this repository.

---

## Integration Summary

| Repository | Role | Key Tech | Depends On |
|-----------|------|----------|------------|
| [Mpesa_Analyzer_App](https://github.com/YourOrg/Mpesa_Analyzer_App) | Data capture & upload | Kotlin, Retrofit, AES-128 | Web App API |
| [Mpesa Analyzer WebApp](https://github.com/YourOrg/Mpesa_Analyzer_WebApp) | Storage, dashboard, API | PHP 8.3, CI4, Shield, MySQL | MySQL database |
| [Mpesa Analyser Docker](https://github.com/YourOrg/Mpesa_Analyser_Docker) | LLM-powered classification | Python, FastAPI, llama.cpp, Qwen2.5 | MySQL database |

---

## Support

- **Email**: [info@chegecache.co.ke](mailto:info@chegecache.co.ke)
- **Website**: [chegecache.co.ke](https://chegecache.co.ke)
