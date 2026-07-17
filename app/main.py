from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from app.config import settings
from app.db.connection import verify_connection, close_engine
from app.db.queries import (
    create_job,
    ensure_jobs_table,
    ensure_tracking_table,
    fetch_unprocessed_sms,
    fetch_unprocessed_sms_by_owner,
    insert_analyzed_transaction,
    mark_processing,
    update_job,
    update_sms_with_parsed,
    upsert_sender_profile,
    upsert_sms_classification,
)
from app.models.schemas import HealthResponse, ProcessingJobResponse, SenderClassification
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


# ── Core processing logic (shared by background & API) ────


async def process_rows(rows: list[dict]) -> dict:
    """Process a list of SMS rows (sender classification + extraction)."""
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

    classifications = await SenderClassifier.classify_batch(classify_input)

    cls_by_number: dict[str, SenderClassification] = {}
    for cls in classifications:
        cls_by_number[cls.sender.upper()] = cls

    senders_processed = 0
    finance_senders_found = 0
    messages_processed = 0
    transactional_inserted = 0
    errors = 0

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

        try:
            await upsert_sender_profile(
                owner=data["owner"],
                number=data["number"],
                name=cls.sender,
                category=cls.category.value,
                is_finance=cls.is_finance,
                confidence=cls.confidence,
            )
        except Exception as e:
            logger.error(f"Failed to upsert sender profile for {data['number']}: {e}")

        # Write classification for ALL SMS regardless of finance status
        for sms_id, body_text in zip(data["sms_ids"], data["bodies"]):
            try:
                direction = "none"
                category = cls.category.value if hasattr(cls.category, 'value') else str(cls.category)
                if cls.is_finance:
                    # Infer direction from body keywords for classification
                    body_lower = body_text.lower()
                    if any(w in body_lower for w in ["received", "credited", "deposit"]):
                        direction = "incoming"
                    elif any(w in body_lower for w in ["sent", "paid", "withdrawn", "transfer to"]):
                        direction = "outgoing"

                await upsert_sms_classification(
                    sms_id=sms_id,
                    sender=data["number"],
                    category=category,
                    direction=direction,
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
            continue

        finance_senders_found += 1
        extractions = await MessageExtractor.extract_batch(data["bodies"])

        for idx, extraction in enumerate(extractions):
            if idx >= len(data["rows"]):
                break
            row = data["rows"][idx]
            sms_id = row["id"]

            try:
                if extraction:
                    await update_sms_with_parsed(
                        sms_id=sms_id,
                        direction=extraction.direction.value if extraction.direction else None,
                        amount=extraction.amount_changed,
                        balance=extraction.amount_after or extraction.amount_before,
                        counterparty=extraction.counterparty,
                        transaction_type=extraction.transaction_type.value if extraction.transaction_type else None,
                        is_transactional=extraction.is_transactional,
                    )
                    if extraction.is_transactional and extraction.amount_changed:
                        await insert_analyzed_transaction(
                            sms_id=sms_id,
                            amount=extraction.amount_changed,
                            counterparty=extraction.counterparty,
                            description=f"{extraction.direction.value if extraction.direction else 'unknown'} | {extraction.transaction_type.value if extraction.transaction_type else 'unknown'}",
                            trans_date=extraction.transaction_time,
                        )
                        transactional_inserted += 1
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

    return {
        "senders_classified": senders_processed,
        "messages_processed": messages_processed,
        "finance_senders_found": finance_senders_found,
        "transactional_inserted": transactional_inserted,
        "errors": errors,
    }


async def run_processing() -> dict:
    await ensure_tracking_table()
    rows = await fetch_unprocessed_sms(settings.batch_size)
    return await process_rows(rows)


# ── Background poller ─────────────────────────────────────


async def poll_loop():
    db_ok = await verify_connection()
    if not db_ok:
        logger.warning("DB not reachable at startup — background poller will retry")

    while _running:
        try:
            db_ok = await verify_connection()
            if db_ok and not _processing_lock.locked():
                async with _processing_lock:
                    result = await run_processing()
                    if result["messages_processed"] > 0:
                        logger.info(f"Processed batch: {result}")
            else:
                logger.debug("DB not reachable or already processing, skipping poll cycle")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Poll cycle error: {e}")

        for _ in range(settings.poll_interval):
            if not _running:
                break
            await asyncio.sleep(1)


# ── Lifespan ──────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _processor_task
    logger.info(f"Starting SMS Finance LLM service — polling every {settings.poll_interval}s")
    _processor_task = asyncio.create_task(poll_loop())
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


app = FastAPI(
    title="SMS Finance LLM Service",
    description="Autonomous DB-to-DB SMS financial processor with local llama.cpp",
    version="1.0.0",
    lifespan=lifespan,
)


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
    """Manually trigger one processing cycle (skips if already running)."""
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
async def process_for_user(user_id: str):
    """Process unprocessed SMS for a specific user.

    The PHP webapp inserts a row into tbl_Processing_Jobs with
    status='queued' before calling this endpoint. This endpoint
    picks it up, runs the LLM pipeline, and marks it done.
    """
    await ensure_tracking_table()
    await ensure_jobs_table()

    job_id = await create_job(user_id)
    await update_job(job_id, status="starting", started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    start = datetime.now()

    rows = await fetch_unprocessed_sms_by_owner(user_id, settings.batch_size)
    if not rows:
        elapsed = int((datetime.now() - start).total_seconds())
        await update_job(
            job_id,
            status="done",
            completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            duration_seconds=elapsed,
            messages_processed=0,
            errors=0,
        )
        return ProcessingJobResponse(
            job_id=job_id, user_id=user_id, status="done",
            messages_processed=0, errors=0, duration_seconds=elapsed,
            started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
            completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    try:
        result = await process_rows(rows)
        elapsed = int((datetime.now() - start).total_seconds())
        await update_job(
            job_id,
            status="done",
            completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            duration_seconds=elapsed,
            messages_processed=result["messages_processed"],
            errors=result["errors"],
        )
        return ProcessingJobResponse(
            job_id=job_id,
            user_id=user_id,
            status="done",
            messages_processed=result["messages_processed"],
            errors=result["errors"],
            duration_seconds=elapsed,
            started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
            completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    except Exception as e:
        elapsed = int((datetime.now() - start).total_seconds())
        await update_job(job_id, status="error", completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), duration_seconds=elapsed)
        logger.error(f"User processing failed for {user_id}: {e}")
        return ProcessingJobResponse(
            job_id=job_id, user_id=user_id, status="error",
            duration_seconds=elapsed,
            started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
            completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
