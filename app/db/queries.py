from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from app.db.connection import get_engine

logger = logging.getLogger(__name__)


def _parse_date_to_mysql(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = str(raw).strip().lower()

    # ISO formats: "2026-08-24 10:33:00", "2026-08-24T10:33:00", "2026-08-24"
    m_iso = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[ t](\d{2}:\d{2}(?::\d{2})?))?", raw)
    if m_iso:
        date_part, time_part = m_iso.groups()
        return f"{date_part} {time_part if time_part else '00:00:00'}"

    # Kenyan formats: "9/7/26 at 6:14 am", "15/7/2026 at 10:30", "9/7/2026"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)?", raw)
    if m:
        d, mo, y, h, mi, ap = m.groups()
        if len(y) == 2:
            y = "20" + y
        h = int(h)
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return f"{y}-{int(mo):02d}-{int(d):02d} {h:02d}:{mi}:00"

    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:
            y = "20" + y
        return f"{y}-{int(mo):02d}-{int(d):02d} 00:00:00"

    return None


# ── Master startup migrations ──────────────────────────────
#
# ensure_all_tables() is the single entry point called at service startup.
# It idempotently creates every table the ML service needs and backfills
# any columns that may be missing from older deployments. This mirrors the
# CodeIgniter migrations so both sides stay in sync; either side can run
# first safely.


async def ensure_all_tables():
    """Create all required ML-service tables and backfill missing columns.

    Safe to call multiple times — every statement uses CREATE TABLE IF NOT EXISTS
    or checks INFORMATION_SCHEMA before ALTER. Call once in the FastAPI lifespan.
    """
    engine = get_engine()
    async with engine.connect() as conn:

        # ── tbl_Sms_Processing ────────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tbl_Sms_Processing (
                sms_id        INT PRIMARY KEY,
                status        VARCHAR(20)  DEFAULT 'pending',
                attempt_count INT          DEFAULT 0,
                last_error    TEXT         NULL,
                processed_at  DATETIME     NULL,
                INDEX idx_sms_proc_status (status)
            )
        """))

        # ── tbl_LLM_Prompts ───────────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tbl_LLM_Prompts (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                prompt_key  VARCHAR(50)  NOT NULL,
                version     INT          NOT NULL,
                title       VARCHAR(255) NOT NULL DEFAULT '',
                body        TEXT         NOT NULL,
                is_active   TINYINT(1)   DEFAULT 0,
                created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_llm_key_ver (prompt_key, version),
                KEY idx_llm_key_active (prompt_key, is_active)
            )
        """))

        # ── tbl_ML_Controls ───────────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tbl_ML_Controls (
                control_key   VARCHAR(50)  NOT NULL PRIMARY KEY,
                control_value VARCHAR(255) NOT NULL,
                updated_at    DATETIME     DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP
            )
        """))

        # ── tbl_Processing_Jobs ───────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tbl_Processing_Jobs (
                id                  INT AUTO_INCREMENT PRIMARY KEY,
                user_id             VARCHAR(100) NOT NULL,
                status              VARCHAR(20)  DEFAULT 'queued',
                started_at          DATETIME     NULL,
                completed_at        DATETIME     NULL,
                duration_seconds    INT          NULL,
                messages_processed  INT          DEFAULT 0,
                errors              INT          DEFAULT 0,
                metadata            JSON         NULL,
                created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_pj_user_status (user_id, status)
            )
        """))
        await conn.commit()

        # ── Backfill missing columns on pre-existing tables ───────────────

        # metadata column on tbl_Processing_Jobs (older deployments may lack it)
        has_meta = await conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = 'tbl_Processing_Jobs'
              AND COLUMN_NAME  = 'metadata'
        """))
        if has_meta.scalar_one() == 0:
            await conn.execute(text(
                "ALTER TABLE tbl_Processing_Jobs ADD COLUMN metadata JSON NULL AFTER errors"
            ))
            await conn.commit()

        # Advisor-insight columns on tbl_Sms (added by 2026-08-24-201500 migration)
        sms_cols_res = await conn.execute(text("""
            SELECT COLUMN_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tbl_Sms'
        """))
        sms_cols = {r[0] for r in sms_cols_res.fetchall()}

        advisor_additions: list[str] = []
        if "sms_counterparty_type" not in sms_cols:
            advisor_additions.append(
                "ADD COLUMN sms_counterparty_type VARCHAR(100) NULL"
            )
        if "sms_is_abnormal" not in sms_cols:
            advisor_additions.append(
                "ADD COLUMN sms_is_abnormal TINYINT(1) NOT NULL DEFAULT 0"
            )
        if "sms_normality_assessment" not in sms_cols:
            advisor_additions.append(
                "ADD COLUMN sms_normality_assessment TEXT NULL"
            )
        if "sms_savings_impact" not in sms_cols:
            advisor_additions.append(
                "ADD COLUMN sms_savings_impact VARCHAR(50) NULL"
            )
        if "sms_advisor_insight" not in sms_cols:
            advisor_additions.append(
                "ADD COLUMN sms_advisor_insight TEXT NULL"
            )

        if advisor_additions:
            alter_sql = "ALTER TABLE tbl_Sms " + ", ".join(advisor_additions)
            await conn.execute(text(alter_sql))
            await conn.commit()
            logger.info(f"Backfilled tbl_Sms columns: {advisor_additions}")

        # ── tbl_LLM_Calls ──────────────────────────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tbl_LLM_Calls (
                id             INT AUTO_INCREMENT PRIMARY KEY,
                job_id         INT          NULL,
                call_type      VARCHAR(20)  NOT NULL,
                model          VARCHAR(100) NULL,
                provider       VARCHAR(50)  NULL,
                prompt_tokens  INT          NULL,
                reply_tokens   INT          NULL,
                latency_ms     INT          NULL,
                batch_size     INT          NULL,
                status         VARCHAR(20)  DEFAULT 'ok',
                error_message  TEXT         NULL,
                created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_llmc_job     (job_id),
                INDEX idx_llmc_type    (call_type),
                INDEX idx_llmc_created (created_at)
            )
        """))
        await conn.commit()

    logger.info("ensure_all_tables: all ML tables and columns verified OK")


# ── LLM call audit log ─────────────────────────────────────


async def log_llm_call(
    call_type: str,
    model: str,
    provider: str,
    latency_ms: int,
    batch_size: int,
    status: str = "ok",
    job_id: Optional[int] = None,
    prompt_tokens: Optional[int] = None,
    reply_tokens: Optional[int] = None,
    error_message: Optional[str] = None,
):
    """Insert one row into tbl_LLM_Calls. Failures are swallowed — audit logging
    must never break the main processing pipeline."""
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(
                text("""
                    INSERT INTO tbl_LLM_Calls
                        (job_id, call_type, model, provider, prompt_tokens,
                         reply_tokens, latency_ms, batch_size, status, error_message, created_at)
                    VALUES
                        (:job_id, :call_type, :model, :provider, :prompt_tokens,
                         :reply_tokens, :latency_ms, :batch_size, :status, :error_message, NOW())
                """),
                {
                    "job_id": job_id,
                    "call_type": call_type,
                    "model": model,
                    "provider": provider,
                    "prompt_tokens": prompt_tokens,
                    "reply_tokens": reply_tokens,
                    "latency_ms": latency_ms,
                    "batch_size": batch_size,
                    "status": status,
                    "error_message": (error_message or "")[:500] if error_message else None,
                },
            )
            await conn.commit()
    except Exception as e:
        logger.warning(f"log_llm_call failed (non-fatal): {e}")


# ── Read unprocessed SMS (Mode B) ─────────────────────────


async def fetch_unprocessed_sms(batch_size: int) -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT s.id, s.sms_number, s.sms_body, s.sms_owner, s.sms_time
                FROM tbl_Sms s
                LEFT JOIN tbl_Sms_Processing p ON p.sms_id = s.id
                WHERE p.sms_id IS NULL
                ORDER BY s.id ASC
                LIMIT :limit
            """),
            {"limit": batch_size},
        )
        rows = result.fetchall()
        return [
            {
                "id": row[0],
                "sms_number": row[1] or "",
                "sms_body": row[2] or "",
                "sms_owner": row[3] or "",
                "sms_time": row[4] or "",
            }
            for row in rows
        ]


# ── Tracking table helpers ─────────────────────────────────


async def ensure_tracking_table():
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS tbl_Sms_Processing (
                    sms_id INT PRIMARY KEY,
                    status VARCHAR(20) DEFAULT 'pending',
                    attempt_count INT DEFAULT 0,
                    last_error TEXT NULL,
                    processed_at DATETIME NULL,
                    INDEX idx_status (status)
                )
            """)
        )
        await conn.commit()


async def mark_processing(sms_id: int, status: str, error: Optional[str] = None):
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                INSERT INTO tbl_Sms_Processing (sms_id, status, attempt_count, last_error, processed_at)
                VALUES (:sid, :status, 1, :error, NOW())
                ON DUPLICATE KEY UPDATE
                    status = :status2,
                    attempt_count = attempt_count + 1,
                    last_error = :error2,
                    processed_at = NOW()
            """),
            {
                "sid": sms_id,
                "status": status,
                "error": error,
                "status2": status,
                "error2": error,
            },
        )
        await conn.commit()


# ── Write parsed data ──────────────────────────────────────


async def upsert_sms_analysis(
    sms_id: int,
    direction: Optional[str],
    amount: Optional[float],
    balance: Optional[float],
    counterparty: Optional[str],
    transaction_type: Optional[str],
    is_transactional: bool,
    category: Optional[str],
    is_finance: Optional[bool],
    confidence: Optional[float],
    method: Optional[str],
    trans_date: Optional[str] = None,
    fee: Optional[float] = None,
    is_reversal: bool = False,
    is_loan: bool = False,
    counterparty_type: Optional[str] = None,
    is_abnormal: bool = False,
    normality_assessment: Optional[str] = None,
    savings_impact: Optional[str] = None,
    advisor_insight: Optional[str] = None,
):
    """Single canonical write: persist classification + parsed data to tbl_Sms.

    tbl_Sms is the single source of truth for per-SMS analysis. The old
    tbl_Sms_Classification and tbl_Analyzed_Transactions tables are now VIEWs
    derived from tbl_Sms, so they must not be written to directly.
    """
    parsed_date = _parse_date_to_mysql(trans_date) if trans_date else None

    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                UPDATE tbl_Sms
                SET
                    sms_direction = :direction,
                    sms_amount = :amount,
                    sms_balance = :balance,
                    sms_counterparty = :counterparty,
                    sms_transaction_type = :transaction_type,
                    sms_is_transactional = :is_transactional,
                    sms_category = :category,
                    sms_is_finance = :is_finance,
                    sms_confidence = :confidence,
                    sms_method = :method,
                    sms_trans_date = :trans_date,
                    sms_fee = :fee,
                    sms_is_reversal = :is_reversal,
                    sms_is_loan = :is_loan,
                    sms_counterparty_type = :counterparty_type,
                    sms_is_abnormal = :is_abnormal,
                    sms_normality_assessment = :normality_assessment,
                    sms_savings_impact = :savings_impact,
                    sms_advisor_insight = :advisor_insight
                WHERE id = :sid
            """),
            {
                "sid": sms_id,
                "direction": direction,
                "amount": amount,
                "balance": balance,
                "counterparty": counterparty,
                "transaction_type": transaction_type,
                "is_transactional": 1 if is_transactional else 0,
                "category": category,
                "is_finance": 1 if is_finance else 0,
                "confidence": confidence,
                "method": method,
                "trans_date": parsed_date,
                "fee": fee if fee is not None else 0.00,
                "is_reversal": 1 if is_reversal else 0,
                "is_loan": 1 if is_loan else 0,
                "counterparty_type": counterparty_type,
                "is_abnormal": 1 if is_abnormal else 0,
                "normality_assessment": normality_assessment,
                "savings_impact": savings_impact,
                "advisor_insight": advisor_insight,
            },
        )
        await conn.commit()


# ── Sender profile helpers ─────────────────────────────────


async def upsert_sender_profile(
    owner: str,
    number: str,
    name: str,
    category: str,
    is_finance: bool,
    confidence: float,
):
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                INSERT INTO tbl_Sender_Profiles
                    (sp_owner, sp_number, sp_name, sp_category, sp_is_finance, sp_confidence, sp_created, sp_updated)
                VALUES
                    (:owner, :number, :name, :category, :is_finance, :confidence, NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                    sp_name = VALUES(sp_name),
                    sp_category = VALUES(sp_category),
                    sp_is_finance = VALUES(sp_is_finance),
                    sp_confidence = VALUES(sp_confidence),
                    sp_updated = NOW()
            """),
            {
                "owner": owner,
                "number": number,
                "name": name,
                "category": category,
                "is_finance": 1 if is_finance else 0,
                "confidence": confidence,
            },
        )
        await conn.commit()


async def get_sender_profile(owner: str, number: str) -> Optional[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT * FROM tbl_Sender_Profiles
                WHERE sp_owner = :owner AND sp_number = :number
            """),
            {"owner": owner, "number": number},
        )
        row = result.fetchone()
        if row:
            return dict(row._mapping)
        return None


async def get_processed_sender_numbers(owner: str) -> set[str]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT DISTINCT sp_number FROM tbl_Sender_Profiles
                WHERE sp_owner = :owner AND sp_is_finance = 1
            """),
            {"owner": owner},
        )
        return {row[0] for row in result.fetchall()}


async def get_allowed_senders() -> dict[str, Optional[str]]:
    """Global "allowed by default" finance senders from tbl_Allowed_Senders.

    Returns a map of upper-cased sender -> category. The caller falls back to
    the hardcoded list when this table is empty (or on any DB error).
    """
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT sender, category FROM tbl_Allowed_Senders")
        )
        return {row[0].upper(): row[1] for row in result.fetchall()}


# ── Prompt version management ─────────────────────────────


async def ensure_prompts_table():
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS tbl_LLM_Prompts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    prompt_key VARCHAR(50) NOT NULL,
                    version INT NOT NULL,
                    title VARCHAR(255) NOT NULL DEFAULT '',
                    body TEXT NOT NULL,
                    is_active TINYINT(1) DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_key_version (prompt_key, version),
                    KEY idx_key_active (prompt_key, is_active)
                )
            """)
        )
        await conn.commit()


async def get_all_prompts() -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT id, prompt_key, version, title, body, is_active, created_at
                FROM tbl_LLM_Prompts
                ORDER BY prompt_key ASC, version DESC
            """)
        )
        return [dict(row._mapping) for row in result.fetchall()]


async def get_active_prompt(key: str) -> Optional[str]:
    """Return the body of the active prompt for a key, or None."""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT body FROM tbl_LLM_Prompts
                WHERE prompt_key = :k AND is_active = 1
                ORDER BY version DESC LIMIT 1
            """),
            {"k": key},
        )
        row = result.fetchone()
        return row[0] if row else None


async def get_max_version(key: str) -> int:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT COALESCE(MAX(version), 0) FROM tbl_LLM_Prompts WHERE prompt_key = :k
            """),
            {"k": key},
        )
        return int(result.scalar_one())


async def deactivate_prompts(key: str):
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("UPDATE tbl_LLM_Prompts SET is_active = 0 WHERE prompt_key = :k"),
            {"k": key},
        )
        await conn.commit()


async def insert_prompt(key: str, title: str, body: str, version: int, is_active: int = 1) -> int:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                INSERT INTO tbl_LLM_Prompts (prompt_key, version, title, body, is_active, created_at)
                VALUES (:k, :v, :t, :b, :a, NOW())
            """),
            {"k": key, "v": version, "t": title, "b": body, "a": is_active},
        )
        await conn.commit()
        return result.lastrowid


async def set_prompt_active(prompt_id: int, key: str):
    await deactivate_prompts(key)
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("UPDATE tbl_LLM_Prompts SET is_active = 1 WHERE id = :id"),
            {"id": prompt_id},
        )
        await conn.commit()


async def delete_prompt(prompt_id: int):
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("DELETE FROM tbl_LLM_Prompts WHERE id = :id"),
            {"id": prompt_id},
        )
        await conn.commit()


# ── Job controls (admin auto on/off) ───────────────────────


async def ensure_controls_table():
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS tbl_ML_Controls (
                    control_key VARCHAR(50) PRIMARY KEY,
                    control_value VARCHAR(255) NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            """)
        )
        await conn.commit()


async def get_control(key: str, default: str = "") -> str:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT control_value FROM tbl_ML_Controls WHERE control_key = :k"),
                {"k": key},
            )
            row = result.fetchone()
            return row[0] if row else default
    except Exception as e:
        logger.warning(f"Could not read control '{key}' ({e}); using default.")
        return default


async def set_control(key: str, value: str):
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                INSERT INTO tbl_ML_Controls (control_key, control_value)
                VALUES (:k, :v)
                ON DUPLICATE KEY UPDATE control_value = VALUES(control_value)
            """),
            {"k": key, "v": value},
        )
        await conn.commit()


async def is_auto_jobs_enabled() -> bool:
    """Whether the background poller / auto jobs may run."""
    value = await get_control("auto_jobs_enabled", "1")
    return value.lower() in {"1", "true", "yes", "on"}


# ── User-triggered processing jobs ─────────────────────────


async def ensure_jobs_table():
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS tbl_Processing_Jobs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(100) NOT NULL,
                    status VARCHAR(20) DEFAULT 'queued',
                    started_at DATETIME NULL,
                    completed_at DATETIME NULL,
                    duration_seconds INT NULL,
                    messages_processed INT DEFAULT 0,
                    errors INT DEFAULT 0,
                    metadata JSON NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_status (user_id, status)
                )
            """)
        )
        # Add metadata column on legacy tables (MySQL 8: check before ALTER).
        col = await conn.execute(
            text("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tbl_Processing_Jobs'
                  AND COLUMN_NAME = 'metadata'
            """)
        )
        if col.scalar_one() == 0:
            await conn.execute(text("ALTER TABLE tbl_Processing_Jobs ADD COLUMN metadata JSON NULL"))
        await conn.commit()


async def create_job(user_id: str) -> int:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                INSERT INTO tbl_Processing_Jobs (user_id, status, created_at)
                VALUES (:user_id, 'queued', NOW())
            """),
            {"user_id": user_id},
        )
        await conn.commit()
        return result.lastrowid


async def update_job(job_id: int, **kwargs):
    sets = []
    params: dict = {"id": job_id}
    for key, val in kwargs.items():
        sets.append(f"{key} = :{key}")
        if isinstance(val, (dict, list)):
            params[key] = json.dumps(val)
        else:
            params[key] = val
    if not sets:
        return
    engine = get_engine()
    async with engine.connect() as conn:
        # Check if the job was cancelled or marked failed externally
        check = await conn.execute(
            text("SELECT status FROM tbl_Processing_Jobs WHERE id = :id"),
            {"id": job_id}
        )
        row = check.fetchone()
        if row and row[0] in ('failed', 'cancelled'):
            logger.info(f"Job {job_id} is already in state '{row[0]}'. Skipping update.")
            return

        await conn.execute(
            text(f"UPDATE tbl_Processing_Jobs SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        await conn.commit()


async def fetch_jobs(limit: int = 100) -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT id, user_id, status, started_at, completed_at,
                       duration_seconds, messages_processed, errors, metadata, created_at
                FROM tbl_Processing_Jobs
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )
        return [dict(row._mapping) for row in result.fetchall()]


async def fetch_unprocessed_sms_by_owner(owner: str, batch_size: int) -> list[dict]:
    engine = get_engine()
    user_id_int = int(owner) if (owner or "").isdigit() else -1

    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT s.id, s.sms_number, s.sms_body, s.sms_owner, s.sms_time
                FROM tbl_Sms s
                LEFT JOIN tbl_Sms_Processing p ON p.sms_id = s.id
                WHERE p.sms_id IS NULL
                  AND (
                    s.sms_owner = :owner 
                    OR (
                        :user_id_int != -1 
                        AND s.sms_owner IN (
                            SELECT DISTINCT s2.sms_owner 
                            FROM tbl_Sms s2
                            INNER JOIN auth_identities i ON i.secret = SHA2(s2.sms_owner, 256)
                            WHERE i.user_id = :user_id_int AND i.type = 'access_token'
                        )
                    )
                  )
                ORDER BY s.id ASC
                LIMIT :limit
            """),
            {"owner": owner, "user_id_int": user_id_int, "limit": batch_size},
        )
        rows = result.fetchall()
        return [
            {
                "id": row[0],
                "sms_number": row[1] or "",
                "sms_body": row[2] or "",
                "sms_owner": row[3] or "",
                "sms_time": row[4] or "",
            }
            for row in rows
        ]


async def fetch_user_financial_aggregation(owner: str) -> dict:
    """Compute financial summary for a user's processed SMS messages."""
    engine = get_engine()
    user_id_int = int(owner) if (owner or "").isdigit() else -1

    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT 
                    COUNT(s.id) as total_transactions,
                    COALESCE(SUM(CASE WHEN s.sms_direction = 'outgoing' THEN s.sms_amount ELSE 0 END), 0) as total_sent,
                    COALESCE(SUM(CASE WHEN s.sms_direction = 'incoming' THEN s.sms_amount ELSE 0 END), 0) as total_received,
                    COALESCE(SUM(s.sms_amount), 0) as total_volume
                FROM tbl_Sms s
                WHERE s.sms_is_transactional = 1
                  AND (
                    s.sms_owner = :owner 
                    OR (
                        :user_id_int != -1 
                        AND s.sms_owner IN (
                            SELECT DISTINCT s2.sms_owner 
                            FROM tbl_Sms s2
                            INNER JOIN auth_identities i ON i.secret = SHA2(s2.sms_owner, 256)
                            WHERE i.user_id = :user_id_int AND i.type = 'access_token'
                        )
                    )
                  )
            """),
            {"owner": owner, "user_id_int": user_id_int},
        )
        row = result.fetchone()
        
        type_res = await conn.execute(
            text("""
                SELECT s.sms_transaction_type, COUNT(*) as cnt
                FROM tbl_Sms s
                WHERE s.sms_is_transactional = 1
                  AND (
                    s.sms_owner = :owner 
                    OR (
                        :user_id_int != -1 
                        AND s.sms_owner IN (
                            SELECT DISTINCT s2.sms_owner 
                            FROM tbl_Sms s2
                            INNER JOIN auth_identities i ON i.secret = SHA2(s2.sms_owner, 256)
                            WHERE i.user_id = :user_id_int AND i.type = 'access_token'
                        )
                    )
                  )
                GROUP BY s.sms_transaction_type
            """),
            {"owner": owner, "user_id_int": user_id_int},
        )
        types = {r[0]: int(r[1]) for r in type_res.fetchall() if r[0] is not None}

        return {
            "transaction_count": int(row[0] or 0) if row else 0,
            "total_sent_money": float(row[1] or 0.0) if row else 0.0,
            "total_received_money": float(row[2] or 0.0) if row else 0.0,
            "total_transaction_volume": float(row[3] or 0.0) if row else 0.0,
            "transaction_types": types,
        }
