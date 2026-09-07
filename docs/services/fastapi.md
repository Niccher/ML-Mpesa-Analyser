# FastAPI Service Handbook — ML Mpesa Analyzer

This document details the code structure and runtime components of the FastAPI service located in `app/`.

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
│   └── admin.py               # Router for /admin/* endpoints
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

## 3. Database Session Handling

- Uses `SQLAlchemy` with `aiomysql` driver (`mysql+aiomysql://...`).
- Database connections use a scoped session factory to prevent connection leaks across async worker routines.
