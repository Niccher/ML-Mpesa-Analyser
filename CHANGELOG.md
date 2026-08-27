# Changelog — ML Mpesa Analyzer (FastAPI LLM Service)

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.2.0] — 2026-08-27

### Added
- **Parallelized LLM calls** — `SenderClassifier` and `Extractor` now use
  `asyncio.gather` for concurrent batch processing, dramatically improving
  throughput on large SMS jobs.
- **Blocked-sender auto-bypass** — processing jobs automatically skip senders
  present on the blocklist without requiring manual intervention or job restart.
- **`seed_prompts.py`** — standalone utility script to seed `classify_sender`
  and `extract_batch` prompt keys into the database via the admin REST API.
- **Model management endpoints**:
  - `POST /admin/models/upload` — streams `.gguf`/`.bin` files in 1 MB chunks.
  - `POST /admin/models/delete` — deletes a model with an active-model guard.
- **GGUF metadata introspection** — architecture, parameter count,
  quantization type, and context window exposed via `read_gguf_metadata`;
  surfaced in `/admin/status` and `/admin/models`.
- **Prompt versioning** — new `tbl_LLM_Prompts` table managed by
  `prompt_manager` service. Edits create new immutable versions; admin CRUD
  endpoints support list / create / activate / delete operations.
- **Canonical SMS write** — single `upsert_sms_analysis` replaces the three
  separate write functions (`update_sms_with_parsed`, `upsert_sms_classification`,
  `insert_analyzed_transaction`). Returns richer metadata per sender and
  per category.
- **`tbl_ML_Controls` job gate** — `is_auto_jobs_enabled()` check prevents
  the background poller, `/process/trigger`, and `/process/for-user` from
  running when auto-jobs are administratively disabled.
- **Job metadata JSON column** on `tbl_Processing_Jobs` — stores model path,
  LLM tuning parameters, sender/SMS breakdowns, duration, and errors.
- **Env-driven llama.cpp tuning** — `LLM_CTX_SIZE`, `LLM_BATCH_SIZE`,
  `N_GPU_LAYERS` applied via `entrypoint.sh` so config changes take effect
  on container restart without rebuilding the image.
- `python-multipart` added to `requirements.txt` (required by upload endpoint).
- Docker Compose healthcheck for the FastAPI service.

### Fixed
- SQL query for unprocessed SMS changed from `p.sms_id IS NOT NULL` to
  `WHERE p.sms_id IS NULL`, eliminating infinite processing loop hangs.
- `asyncio.gather` usage corrected in classifier and extractor to avoid
  nested event-loop errors.
- Admin job metadata now records `status=disabled` when auto-jobs gate is
  closed, making job history accurate for audit.

---

## [1.1.0] — 2026-08-11

### Added
- Model and admin management layer.
- DB-prompt overrides with hardcoded-DEFAULT fallback.
- Auto-job control (`is_auto_jobs_enabled`) and per-job metadata storage.
- `GET /admin/allowed/defaults` for the webapp's hardcoded sender fallback.

---

## [1.0.0] — 2026-07-20

### Added
- Initial FastAPI LLM classification service with llama.cpp backend.
- `POST /process/for-user` per-user SMS processing endpoint with job tracking.
- Docker Compose with environment-variable templating and shared network.
- `SenderClassifier` and `Extractor` services with prompt-based LLM calls.
- PostgreSQL integration via `asyncpg`.
- Background polling worker with configurable interval.
