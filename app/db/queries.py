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
    raw = raw.strip().lower()

    # Kenyan formats: "9/7/26 at 6:14 am", "15/7/2026 at 10:30", "9/7/2026"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)", raw)
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
        return f"{y}-{int(mo):02d}-{int(d):02d}"

    return None


# ── Read unprocessed SMS (Mode B) ─────────────────────────


async def fetch_unprocessed_sms(batch_size: int) -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT s.id, s.sms_number, s.sms_body, s.sms_owner, s.sms_time
                FROM tbl_Sms s
                LEFT JOIN tbl_Sms_Processing p ON p.sms_id = s.id
                WHERE (p.sms_id IS NULL OR p.status = 'error')
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


async def update_sms_with_parsed(
    sms_id: int,
    direction: Optional[str],
    amount: Optional[float],
    balance: Optional[float],
    counterparty: Optional[str],
    transaction_type: Optional[str],
    is_transactional: bool,
):
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
                    sms_is_transactional = :is_transactional
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
            },
        )
        await conn.commit()


async def insert_analyzed_transaction(
    sms_id: int,
    amount: Optional[float],
    counterparty: Optional[str],
    description: Optional[str],
    trans_date: Optional[str],
):
    if amount is None or amount == 0:
        return

    parsed_date = _parse_date_to_mysql(trans_date)

    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                INSERT INTO tbl_Analyzed_Transactions
                    (orig_sms_int_id, amount, counterparty, description, trans_date, created_at)
                VALUES
                    (:sid, :amount, :counterparty, :description, :trans_date, NOW())
                ON DUPLICATE KEY UPDATE
                    amount = VALUES(amount),
                    counterparty = VALUES(counterparty),
                    description = VALUES(description)
            """),
            {
                "sid": sms_id,
                "amount": amount,
                "counterparty": counterparty,
                "description": description,
                "trans_date": parsed_date,
            },
        )
        await conn.commit()


# ── Classification helpers ─────────────────────────────────


async def upsert_sms_classification(
    sms_id: int,
    sender: str,
    category: str,
    direction: str,
    is_finance: bool,
    confidence: float,
    method: str = "llm",
):
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                INSERT INTO tbl_Sms_Classification (sms_id, sender, category, direction, is_finance, method, confidence, created_at)
                VALUES (:sid, :sender, :category, :direction, :is_finance, :method, :confidence, NOW())
                ON DUPLICATE KEY UPDATE
                    sender = VALUES(sender),
                    category = VALUES(category),
                    direction = VALUES(direction),
                    is_finance = VALUES(is_finance),
                    method = VALUES(method),
                    confidence = VALUES(confidence)
            """),
            {
                "sid": sms_id,
                "sender": sender,
                "category": category,
                "direction": direction,
                "is_finance": 1 if is_finance else 0,
                "method": method,
                "confidence": confidence,
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
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_status (user_id, status)
                )
            """)
        )
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
        params[key] = val
    if not sets:
        return
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text(f"UPDATE tbl_Processing_Jobs SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        await conn.commit()


async def fetch_unprocessed_sms_by_owner(owner: str, batch_size: int) -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT s.id, s.sms_number, s.sms_body, s.sms_owner, s.sms_time
                FROM tbl_Sms s
                LEFT JOIN tbl_Sms_Processing p ON p.sms_id = s.id
                WHERE (p.sms_id IS NULL OR p.status = 'error')
                  AND s.sms_owner = :owner
                ORDER BY s.id ASC
                LIMIT :limit
            """),
            {"owner": owner, "limit": batch_size},
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
