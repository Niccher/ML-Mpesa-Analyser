# FastAPI Service Handbook — ML Mpesa Analyzer

This document details the code structure, background routines, telemetry endpoint, and process management of the FastAPI service located in `app/`.

---

## 1. Codebase Directory Layout

```
app/
├── main.py                    # Application lifespan, background poller task, core routes
├── config.py                  # Pydantic Settings reading environment variables
├── db/
│   ├── connection.py          # Asynchronous SQLAlchemy engine & sessionmaker
│   └── queries.py             # SQL queries, canonical updates, job audit logging
├── models/
│   └── schemas.py             # Pydantic request/response schemas and enums
├── routers/
│   └── admin.py               # Router for /admin/* (telemetry, models, prompts, controls)
├── services/
│   ├── classifier.py          # Known-dict lookup & LLM sender classification
│   ├── extractor.py           # Batch transaction parser & JSON adherence engine
│   ├── llm_service.py         # OpenAI-compatible HTTP client (httpx)
│   ├── prompt_manager.py      # Resolves active DB prompts vs hardcoded defaults
│   └── gguf_metadata.py       # GGUF file binary header parser
└── utils/
    └── prompt_templates.py    # Default prompts & curated Kenyan finance dictionary
```

---

## 2. Background Poller Mechanism

Implemented via `asyncio.create_task` during application startup (`app/main.py` lifespan context):

1. Wakes up every `POLL_INTERVAL` (default: 30s).
2. Verifies `tbl_ML_Controls.auto_jobs_enabled`. If disabled, sleeps until next tick.
3. Queries `tbl_Sms` for unprocessed or errored records (`app/db/queries.py:get_unprocessed_sms`).
4. Groups batch items by sender phone number.
5. Invokes `classifier.py` for unknown senders and `extractor.py` for finance messages.
6. Performs atomic canonical write to `tbl_Sms` via `queries.py:upsert_sms_analysis`.

---

## 3. Real-Time Telemetry Endpoint (`/admin/telemetry`)

Located in `app/routers/admin.py`, this endpoint supplies live metrics to the WebApp control center:

- **FastAPI Process Vitals**: Extracts PID, resident memory (RSS), and virtual memory via `psutil`.
- **Llama Server Daemon Vitals**: Detects the `llama-server` process ID, memory footprint, active port, and uptime.
- **Active Model Metrics**: Reads active GGUF model path, parameter count, quantization method, and context window size.
- **Queue Diagnostics**: Reports pending unclassified SMS count and active job processing state.

---

## 4. Llama-Server Process Management

When an admin activates a new model preset from the WebApp:

1. `_restart_llama_server()` sends `SIGTERM` to the active daemon.
2. Waits gracefully for socket cleanup.
3. Spawns a new `llama-server` sub-process with optimized flags:
   - `-m <model_path>`
   - `-c <context_size>` (default 4096 / 8192)
   - `-b <batch_size>` (default 512)
   - `-t <cpu_threads>` (derived from available host cores)
   - `--port 8080`
4. Performs health check loop against `http://localhost:8080/health` before marking the model ready.\n