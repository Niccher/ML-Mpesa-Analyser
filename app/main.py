from __future__ import annotations

import asyncio
import base64
import logging
import os
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from app.config import settings
from app.db.connection import verify_connection, close_engine
from app.db.queries import (
    create_job,
    ensure_all_tables,
    fetch_unprocessed_sms,
    fetch_unprocessed_sms_by_owner,
    fetch_user_financial_aggregation,
    is_auto_jobs_enabled,
    log_llm_call,
    mark_processing,
    update_job,
    upsert_sender_profile,
    upsert_sms_analysis,
)
from app.models.schemas import HealthResponse, ProcessingJobResponse, SenderClassification
from app.routers.admin import router as admin_router
from app.services.classifier import SenderClassifier
from app.services.extractor import MessageExtractor
from app.services.llm_service import llm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_running = True
_processor_task: Optional[asyncio.Task] = None
_processing_lock = asyncio.Lock()

# Fix #4 — per-user lock so two simultaneous calls for the same user
# don't double-process the same SMS rows.
_user_locks: dict[str, asyncio.Lock] = {}


# ── Core processing logic (shared by background & API) ────


async def process_rows(rows: list[dict], job_id: Optional[int] = None) -> dict:
    """Process a list of SMS rows (sender classification + extraction).

    Args:
        rows:   SMS rows fetched from DB.
        job_id: Optional tbl_Processing_Jobs id — passed through to log_llm_call
                so every LLM API call is linked to the triggering job.
    """
    if not rows:
        return {"senders_classified": 0, "messages_processed": 0, "finance_senders_found": 0, "transactional_inserted": 0, "errors": 0}

    sender_map: dict[str, dict] = {}
    for row in rows:
        key = f"{row['sms_owner']}||{row['sms_number']}"
        if key not in sender_map:
            sender_map[key] = {
                "owner": row["sms_owner"],
                "number": row["sms_number"],
                "sms_ids": [],
                "bodies": [],
                "rows": [],
            }
        sender_map[key]["sms_ids"].append(row["id"])
        try:
            decoded = base64.b64decode(row["sms_body"]).decode("utf-8", errors="replace")
        except Exception:
            decoded = row["sms_body"] or ""
        sender_map[key]["bodies"].append(decoded)
        sender_map[key]["rows"].append(row)

    classify_input = {}
    for key, data in sender_map.items():
        classify_input[data["number"] or f"unknown_{key}"] = data["bodies"]

    # SenderClassifier.classify_batch returns classifications + per-call results
    classifications, classify_call_results = await SenderClassifier.classify_batch(classify_input)

    # Fix #3 — log every classify LLM call to the audit table
    for cr in classify_call_results:
        await log_llm_call(
            call_type="classify",
            model=cr.model,
            provider=cr.provider,
            latency_ms=cr.latency_ms,
            batch_size=1,
            status="fallback" if cr.used_fallback else "ok",
            job_id=job_id,
            prompt_tokens=cr.prompt_tokens,
            reply_tokens=cr.reply_tokens,
        )

    cls_by_number: dict[str, SenderClassification] = {}
    for cls in classifications:
        cls_by_number[cls.sender.upper()] = cls

    senders_processed = 0
    senders_finance = 0
    senders_unwanted = 0
    messages_processed = 0
    sms_total = len(rows)
    sms_finance = 0
    sms_unwanted = 0
    sms_skipped = 0
    transactional_inserted = 0
    errors = 0

    # Per-sender + per-category + per-direction detail for the report modal.
    senders_detail: list[dict] = []
    category_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {"incoming": 0, "outgoing": 0, "none": 0}

    for key, data in sender_map.items():
        sender_upper = (data["number"] or "").upper().strip()
        cls = cls_by_number.get(sender_upper)
        if cls is None:
            cls = SenderClassification(
                sender=data["number"],
                is_finance=False,
                confidence=0.0,
                category="Non-Finance",
                reasoning="Not classified.",
            )
        senders_processed += 1
        if cls.is_finance:
            senders_finance += 1
            sms_finance += len(data["sms_ids"])
        else:
            senders_unwanted += 1
            sms_unwanted += len(data["sms_ids"])
            sms_skipped += len(data["sms_ids"])

        category = cls.category.value if hasattr(cls.category, 'value') else str(cls.category)
        category_counts[category] = category_counts.get(category, 0) + len(data["sms_ids"])
        parsed_count = 0
        sender_dirs: dict[str, int] = {"incoming": 0, "outgoing": 0, "none": 0}

        try:
            await upsert_sender_profile(
                owner=data["owner"],
                number=data["number"],
                name=cls.sender,
                category=category,
                is_finance=cls.is_finance,
                confidence=cls.confidence,
            )
        except Exception as e:
            logger.error(f"Failed to upsert sender profile for {data['number']}: {e}")

        # Write classification for ALL SMS regardless of finance status.
        # Parsed fields are filled in below for finance senders.
        for sms_id, body_text in zip(data["sms_ids"], data["bodies"]):
            try:
                direction = "none"
                if cls.is_finance:
                    # Infer direction from body keywords for classification
                    body_lower = body_text.lower()
                    if any(w in body_lower for w in ["received", "credited", "deposit"]):
                        direction = "incoming"
                    elif any(w in body_lower for w in ["sent", "paid", "withdrawn", "transfer to"]):
                        direction = "outgoing"

                sender_dirs[direction] = sender_dirs.get(direction, 0) + 1
                direction_counts[direction] = direction_counts.get(direction, 0) + 1

                await upsert_sms_analysis(
                    sms_id=sms_id,
                    direction=direction,
                    amount=None,
                    balance=None,
                    counterparty=None,
                    transaction_type=None,
                    is_transactional=False,
                    category=category,
                    is_finance=cls.is_finance,
                    confidence=cls.confidence,
                    method="llm",
                )
            except Exception as e:
                logger.error(f"Failed to write classification for SMS {sms_id}: {e}")

        if not cls.is_finance:
            for sms_id in data["sms_ids"]:
                try:
                    await mark_processing(sms_id, "skipped", "Non-finance sender")
                except Exception:
                    pass
            senders_detail.append({
                "sender": data["number"],
                "category": category,
                "is_finance": False,
                "confidence": cls.confidence,
                "sms_count": len(data["sms_ids"]),
                "parsed_count": 0,
                "directions": sender_dirs,
            })
            continue

        # Fix #3 — extract_batch now returns (extractions, list[LLMCallResult])
        extractions, extract_call_results = await MessageExtractor.extract_batch(data["bodies"])

        # Log every extract LLM call to the audit table
        for cr in extract_call_results:
            await log_llm_call(
                call_type="extract",
                model=cr.model,
                provider=cr.provider,
                latency_ms=cr.latency_ms,
                batch_size=len(data["bodies"]),
                status="fallback" if cr.used_fallback else "ok",
                job_id=job_id,
                prompt_tokens=cr.prompt_tokens,
                reply_tokens=cr.reply_tokens,
            )

        for idx, extraction in enumerate(extractions):
            if idx >= len(data["rows"]):
                break
            row = data["rows"][idx]
            sms_id = row["id"]

            try:
                if extraction:
                    await upsert_sms_analysis(
                        sms_id=sms_id,
                        direction=extraction.direction.value if extraction.direction else None,
                        amount=extraction.amount_changed,
                        balance=extraction.amount_after or extraction.amount_before,
                        counterparty=extraction.counterparty,
                        transaction_type=extraction.transaction_type.value if extraction.transaction_type else None,
                        is_transactional=extraction.is_transactional,
                        category=extraction.category if extraction.category else category,
                        is_finance=cls.is_finance,
                        confidence=cls.confidence,
                        method="llm",
                        trans_date=extraction.transaction_time,
                        fee=extraction.fee,
                        is_reversal=extraction.is_reversal,
                        is_loan=extraction.is_loan,
                        counterparty_type=extraction.counterparty_type,
                        is_abnormal=extraction.is_abnormal,
                        normality_assessment=extraction.normality_assessment,
                        savings_impact=extraction.savings_impact,
                        advisor_insight=extraction.advisor_insight,
                    )
                    if extraction.is_transactional and extraction.amount_changed:
                        transactional_inserted += 1
                    parsed_count += 1
                    await mark_processing(sms_id, "done")
                else:
                    await mark_processing(sms_id, "error", "LLM returned invalid data")
                messages_processed += 1
            except Exception as e:
                logger.error(f"Failed to process SMS {sms_id}: {e}")
                errors += 1
                try:
                    await mark_processing(sms_id, "error", str(e)[:500])
                except Exception:
                    pass

        senders_detail.append({
            "sender": data["number"],
            "category": category,
            "is_finance": True,
            "confidence": cls.confidence,
            "sms_count": len(data["sms_ids"]),
            "parsed_count": parsed_count,
            "directions": sender_dirs,
        })

    return {
        "senders_classified": senders_processed,
        "senders_total": senders_processed,
        "senders_finance": senders_finance,
        "senders_unwanted": senders_unwanted,
        "messages_processed": messages_processed,
        "sms_total": sms_total,
        "sms_finance": sms_finance,
        "sms_unwanted": sms_unwanted,
        "sms_skipped": sms_skipped,
        "finance_senders_found": senders_finance,
        "transactional_inserted": transactional_inserted,
        "errors": errors,
        "senders_detail": senders_detail,
        "category_counts": category_counts,
        "direction_counts": direction_counts,
    }


async def run_processing() -> dict:
    # Refresh the allowed-senders lookup (DB first, hardcoded fallback).
    await SenderClassifier.reload_allowed()

    await ensure_all_tables()
    batch_size = settings.external_batch_size if settings.llm_engine == "external" else settings.batch_size
    rows = await fetch_unprocessed_sms(batch_size)
    return await process_rows(rows)


# ── Background poller ─────────────────────────────────────


async def poll_loop():
    db_ok = await verify_connection()
    if not db_ok:
        logger.warning("DB not reachable at startup — background poller will retry")

    while _running:
        try:
            db_ok = await verify_connection()
            if not db_ok:
                logger.debug("DB not reachable, skipping poll cycle")
            elif not await is_auto_jobs_enabled():
                logger.info("Auto jobs are disabled (admin toggle) — poller idle")
            elif not _processing_lock.locked():
                async with _processing_lock:
                    result = await run_processing()
                    if result["messages_processed"] > 0:
                        logger.info(f"Processed batch: {result}")
            else:
                logger.debug("Already processing, skipping poll cycle")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Poll cycle error: {e}")

        poll_interval = settings.external_poll_interval if settings.llm_engine == "external" else settings.poll_interval
        for _ in range(poll_interval):
            if not _running:
                break
            await asyncio.sleep(1)


# ── Lifespan ──────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _processor_task
    # Ensure the prompt-versioning and controls tables exist first
    try:
        if await verify_connection():
            await ensure_all_tables()
            # Dynamic settings hot-reload from database
            await settings.reload_from_db()
    except Exception as e:
        logger.warning(f"Could not ensure ML tables or load configs at startup: {e}")

    logger.info(f"Starting SMS Finance LLM service — polling every {settings.poll_interval}s")
    _processor_task = asyncio.create_task(poll_loop())
    # Prime the allowed-senders lookup once at startup.
    await SenderClassifier.reload_allowed()

    yield
    logger.info("Shutting down...")
    _running = False
    if _processor_task:
        _processor_task.cancel()
        try:
            await _processor_task
        except asyncio.CancelledError:
            pass
    await llm.close()
    await close_engine()



def _job_metadata(user_id: str, result: dict, status: str, duration: int, error: str = "") -> dict:
    """Build a rich metadata payload for a processing job."""
    is_external = settings.llm_engine == "external"

    # Common fields always present
    meta: dict = {
        "user_id": user_id,
        "status": status,
        "duration_seconds": duration,
        "error": error or None,
        # Engine marker — key field for the UI to branch on
        "llm_engine": settings.llm_engine,
        # Sender breakdown
        "senders_total": result.get("senders_total", 0),
        "senders_finance": result.get("senders_finance", 0),
        "senders_unwanted": result.get("senders_unwanted", 0),
        # SMS breakdown
        "sms_total": result.get("sms_total", 0),
        "sms_finance": result.get("sms_finance", 0),
        "sms_unwanted": result.get("sms_unwanted", 0),
        "sms_skipped": result.get("sms_skipped", 0),
        "messages_processed": result.get("messages_processed", 0),
        "transactional_inserted": result.get("transactional_inserted", 0),
        "errors": result.get("errors", 0),
        # Per-sender / category / direction detail
        "senders_detail": result.get("senders_detail", []),
        "category_counts": result.get("category_counts", {}),
        "direction_counts": result.get("direction_counts", {}),
    }

    if is_external:
        # External engine fields
        meta.update({
            "model": settings.llm_external_model,
            "model_provider": settings.llm_external_provider,
            "model_base_url": settings.llm_external_base_url,
            "llm_max_tokens": settings.llm_external_max_tokens,
            "llm_temperature": settings.llm_external_temperature,
            "sms_batch_size": settings.external_batch_size,
            "max_retries": settings.external_max_retries,
            "poll_interval": settings.external_poll_interval,
            # Fallback info
            "fallback_enabled": settings.llm_fallback_enabled,
            "fallback_provider": settings.llm_fallback_provider if settings.llm_fallback_enabled else None,
            "fallback_model": settings.llm_fallback_model if settings.llm_fallback_enabled else None,
        })
    else:
        # Local engine fields
        meta.update({
            "model": settings.llm_model,
            "model_provider": settings.llm_provider,
            "model_path": os.getenv("MODEL_PATH", ""),
            "model_base_url": settings.llm_base_url,
            "llm_max_tokens": settings.llm_max_tokens,
            "llm_temperature": settings.llm_temperature,
            "llm_ctx_size": settings.llm_ctx_size,
            "llm_batch_size": settings.llm_batch_size,
            "n_gpu_layers": settings.n_gpu_layers,
            "sms_batch_size": settings.batch_size,
            "max_retries": settings.max_retries,
            "poll_interval": settings.poll_interval,
        })

    return meta


from fastapi.staticfiles import StaticFiles

openapi_tags = [
    {"name": "System Health", "description": "Liveness probes, DB connection status, and LLM model provider telemetry."},
    {"name": "Autonomous Pipeline", "description": "DB-to-DB background processing triggers, batch rescan execution, and job status."},
    {"name": "Classification & Extraction", "description": "Sender categorization and financial payload extraction endpoints."},
]

app = FastAPI(
    title="Universal Financial Intelligence Microservice",
    description="""
### 🧠 Universal Multi-Channel Financial Analytics Microservice

An autonomous **DB-to-DB SMS & Financial Transaction Processor** powered by local `llama.cpp` / Qwen models.

* **Multi-Source Financial Classification**: Categorizes transactions across Banks, Mobile Money, SACCOs, Fintechs, and Cards.
* **Autonomous Worker Loop**: Asynchronously processes unprocessed transaction payloads with per-user lock isolation.
* **Telemetry & Hit Tracking**: Logs per-transaction LLM execution time, token usage, and classification confidence.
""",
    version="1.4.0",
    contact={
        "name": "Financial Analyzer Ecosystem",
        "url": "https://github.com/niccher/Mpesa_Analyzer_App",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
    openapi_tags=openapi_tags,
    lifespan=lifespan,
    swagger_favicon_url="/static/favicon.ico",
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.include_router(admin_router)


# ── Endpoints ─────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health():
    db_ok = await verify_connection()
    return HealthResponse(
        status="ok",
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        db_configured=db_ok,
    )


@app.post("/process/trigger")
async def trigger_processing():
    """Manually trigger one processing cycle (skips if already running).

    Honours the admin auto-jobs toggle: when auto jobs are disabled, manual
    triggers are blocked too.
    """
    if not await is_auto_jobs_enabled():
        return {"status": "disabled", "reason": "Auto jobs are disabled by admin"}
    if _processing_lock.locked():
        return {"status": "skipped", "reason": "already processing"}
    async with _processing_lock:
        result = await run_processing()
    return result


@app.post("/process/db")
async def process_db():
    """Alias for /process/trigger — one processing cycle."""
    return await trigger_processing()


@app.post("/process/for-user/{user_id}", response_model=ProcessingJobResponse)
async def process_for_user(user_id: str, job_id: Optional[int] = None):
    """Trigger LLM processing for a user — returns immediately with a job_id.

    If a job is already running for this user, this request will pre-empt/kill
    it in the database. The running job's background thread will detect the status
    change, exit cleanly, release the lock, and allow the new job to run.
    """
    # Fix #5 — startup ensure_all_tables() covers table creation.

    user_lock = _user_locks.setdefault(user_id, asyncio.Lock())
    if user_lock.locked():
        # Preempt the running job: find the active job and mark it as 'failed' (preempted)
        active_job_id = 0
        try:
            from app.db.connection import get_engine as _ge
            from sqlalchemy import text as _text
            engine = _ge()
            async with engine.connect() as conn:
                row = await conn.execute(
                    _text("SELECT id FROM tbl_Processing_Jobs WHERE user_id=:u AND status IN ('queued','starting','processing') ORDER BY id DESC LIMIT 1"),
                    {"u": user_id},
                )
                r = row.fetchone()
                if r:
                    active_job_id = r[0]
                    # Update its status to 'failed' so the loop knows to stop
                    await conn.execute(
                        _text("UPDATE tbl_Processing_Jobs SET status='failed', completed_at=NOW(), metadata=JSON_SET(COALESCE(metadata, '{}'), '$.error', 'Preempted by a new job run.') WHERE id=:id"),
                        {"id": active_job_id}
                    )
                    await conn.commit()
                    logger.info(f"Preempted existing active job {active_job_id} for user {user_id}.")
        except Exception as e:
            logger.warning(f"Failed to preempt active job: {e}")

        # Wait briefly for the lock to release (up to 3 seconds)
        for _ in range(30):
            if not user_lock.locked():
                break
            await asyncio.sleep(0.1)

        # If it's still locked, return already_running
        if user_lock.locked():
            return ProcessingJobResponse(
                job_id=active_job_id or job_id or 0,
                user_id=user_id,
                status="already_running",
                started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )

    if not await is_auto_jobs_enabled():
        if job_id is None:
            job_id = await create_job(user_id)
        await update_job(job_id, status="disabled", completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        return ProcessingJobResponse(
            job_id=job_id, user_id=user_id, status="disabled",
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    # Create job record immediately so the caller has an id to poll
    if job_id is None:
        job_id = await create_job(user_id)
    await update_job(job_id, status="starting", started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # Spawn the actual work as a detached background task.
    # The HTTP response is sent NOW; the task runs independently.
    asyncio.ensure_future(_run_user_job(user_id, job_id, user_lock))

    return ProcessingJobResponse(
        job_id=job_id,
        user_id=user_id,
        status="starting",
        started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )



async def _run_user_job(user_id: str, job_id: int, user_lock: asyncio.Lock):
    """Background task: run the full batch loop for a user.

    Acquires the per-user lock, processes all unprocessed SMS in batches,
    updates progress checkpoints, and releases the lock when done.
    Checks the database before every batch; if the job status has been set
    to 'failed' or 'cancelled' externally, it terminates immediately.
    Always releases the lock — even on exception — so future requests aren't blocked.
    """
    # Dynamic settings hot-reload from database (contains engine config selection)
    await settings.reload_from_db()

    async with user_lock:
        start = datetime.now()
        batch_size = settings.external_batch_size if settings.llm_engine == "external" else settings.batch_size

        total_messages_processed = 0
        total_errors = 0
        total_senders = 0
        total_senders_finance = 0
        total_senders_unwanted = 0
        total_sms = 0
        total_sms_finance = 0
        total_sms_unwanted = 0
        total_sms_skipped = 0
        total_transactional_inserted = 0
        combined_senders_detail: list[dict] = []
        combined_category_counts: dict[str, int] = {}
        combined_direction_counts: dict[str, int] = {"incoming": 0, "outgoing": 0, "none": 0}
        iterations = 0

        engine = None
        try:
            from app.db.connection import get_engine as _ge
            from sqlalchemy import text as _text
            engine = _ge()
        except Exception:
            pass

        try:
            while True:
                # Check database status: stop immediately if cancelled/stopped by admin
                if engine:
                    try:
                        async with engine.connect() as conn:
                            check = await conn.execute(
                                _text("SELECT status FROM tbl_Processing_Jobs WHERE id = :id"),
                                {"id": job_id}
                            )
                            row = check.fetchone()
                            if row and row[0] in ('failed', 'cancelled'):
                                logger.info(f"Job {job_id} cancelled externally. Stopping processing loop.")
                                return
                    except Exception as e:
                        logger.warning(f"Could not verify job status in loop: {e}")

                if engine:
                    try:
                        async with engine.connect() as conn:
                            user_id_int = int(user_id) if (user_id or "").isdigit() else -1
                            if user_id_int != -1:
                                await conn.execute(
                                    _text("""
                                        INSERT INTO tbl_Sms_Processing (sms_id, status, attempt_count, last_error, processed_at)
                                        SELECT s.id, 'skipped', 1, 'Blocked Sender', NOW()
                                        FROM tbl_Sms s
                                        LEFT JOIN tbl_Sms_Processing p ON p.sms_id = s.id
                                        INNER JOIN tbl_Blocked_Senders bs ON UPPER(TRIM(bs.sender)) = UPPER(TRIM(s.sms_number)) AND bs.user_id = :user_id
                                        WHERE p.sms_id IS NULL
                                          AND s.sms_owner IN (
                                            SELECT DISTINCT s2.sms_owner 
                                            FROM tbl_Sms s2
                                            INNER JOIN auth_identities i ON i.secret = SHA2(s2.sms_owner, 256)
                                            WHERE i.user_id = :user_id AND i.type = 'access_token'
                                          )
                                    """),
                                    {"user_id": user_id_int}
                                )
                                await conn.commit()
                    except Exception as e:
                        logger.warning(f"Could not auto-skip blocked senders in loop: {e}")

                rows = await fetch_unprocessed_sms_by_owner(user_id, batch_size)
                if not rows:
                    break

                iterations += 1

                current_senders = list(set(row["sms_number"] for row in rows if row.get("sms_number")))
                # Fix #2 — progressive checkpoint with running totals
                await update_job(
                    job_id,
                    status="processing",
                    messages_processed=total_messages_processed,
                    errors=total_errors,
                    metadata={
                        "iteration": iterations,
                        "sms_done_so_far": total_messages_processed,
                        "last_batch_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "llm_engine": settings.llm_engine,
                        "model": settings.llm_external_model if settings.llm_engine == "external" else settings.llm_model,
                        "model_provider": settings.llm_external_provider if settings.llm_engine == "external" else settings.llm_provider,
                        "current_senders": current_senders,
                    },
                )

                res = await process_rows(rows, job_id=job_id)

                total_messages_processed += res.get("messages_processed", 0)
                total_errors            += res.get("errors", 0)
                total_senders           += res.get("senders_total", 0)
                total_senders_finance   += res.get("senders_finance", 0)
                total_senders_unwanted  += res.get("senders_unwanted", 0)
                total_sms               += res.get("sms_total", 0)
                total_sms_finance       += res.get("sms_finance", 0)
                total_sms_unwanted      += res.get("sms_unwanted", 0)
                total_sms_skipped       += res.get("sms_skipped", 0)
                total_transactional_inserted += res.get("transactional_inserted", 0)

                if isinstance(res.get("senders_detail"), list):
                    combined_senders_detail.extend(res["senders_detail"])
                for cat, cnt in res.get("category_counts", {}).items():
                    combined_category_counts[cat] = combined_category_counts.get(cat, 0) + cnt
                for dir_k, cnt in res.get("direction_counts", {}).items():
                    combined_direction_counts[dir_k] = combined_direction_counts.get(dir_k, 0) + cnt

            elapsed = int((datetime.now() - start).total_seconds())
            financial_agg = await fetch_user_financial_aggregation(user_id)
            speed = round(total_messages_processed / max(1, elapsed), 1)

            combined_result = {
                "senders_total": total_senders, "senders_finance": total_senders_finance,
                "senders_unwanted": total_senders_unwanted, "sms_total": total_sms,
                "sms_finance": total_sms_finance, "sms_unwanted": total_sms_unwanted,
                "sms_skipped": total_sms_skipped, "messages_processed": total_messages_processed,
                "transactional_inserted": total_transactional_inserted, "errors": total_errors,
                "senders_detail": combined_senders_detail,
                "category_counts": combined_category_counts,
                "direction_counts": combined_direction_counts,
            }

            meta = _job_metadata(user_id, combined_result, status="done", duration=elapsed)
            meta["processing_rate_sms_per_sec"] = speed
            meta["iterations"] = iterations
            meta["aggregation"] = financial_agg

            await update_job(
                job_id,
                status="done",
                completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                duration_seconds=elapsed,
                messages_processed=total_messages_processed,
                errors=total_errors,
                metadata=meta,
            )
            logger.info(f"Job {job_id} for user {user_id} completed: {total_messages_processed} messages, {total_errors} errors, {elapsed}s")

        except Exception as e:
            elapsed = int((datetime.now() - start).total_seconds())
            meta = _job_metadata(user_id, {}, status="error", duration=elapsed, error=str(e)[:500])
            try:
                await update_job(job_id, status="error",
                                 completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 duration_seconds=elapsed, metadata=meta)
            except Exception:
                pass
            logger.error(f"Job {job_id} for user {user_id} failed: {e}")






