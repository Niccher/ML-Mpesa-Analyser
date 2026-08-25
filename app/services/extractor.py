from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from pydantic import ValidationError

from app.config import settings
from app.models.schemas import MessageExtraction
from app.services.llm_service import LLMCallResult, llm

logger = logging.getLogger(__name__)


class MessageExtractor:
    @staticmethod
    def _validate_extraction(raw: dict, original_body: str) -> Optional[MessageExtraction]:
        try:
            raw["body"] = original_body[:120]
            return MessageExtraction(**raw)
        except ValidationError as e:
            logger.warning(f"Schema validation failed for message: {e}")
            return None

    @classmethod
    async def extract_batch(
        cls, sms_bodies: list[str]
    ) -> tuple[list[Optional[MessageExtraction]], list[LLMCallResult]]:
        """Process all bodies in chunks.

        Returns:
            results      – one Optional[MessageExtraction] per input body
            call_results – one LLMCallResult per LLM API call made
        """
        if not sms_bodies:
            return [], []

        # Fix #1 — use external_batch_size when engine is external, not the
        # local batch_size (which defaults to 5).  This reduces API call count
        # from N/5 to N/100 when EXTERNAL_BATCH_SIZE=100.
        chunk_size = (
            settings.external_batch_size
            if settings.llm_engine == "external"
            else settings.batch_size
        )

        chunks = [sms_bodies[i: i + chunk_size] for i in range(0, len(sms_bodies), chunk_size)]
        
        # Run chunks concurrently
        tasks = [cls._process_chunk(chunk, i * chunk_size) for i, chunk in enumerate(chunks)]
        chunk_results = await asyncio.gather(*tasks)

        results: list[Optional[MessageExtraction]] = []
        call_results: list[LLMCallResult] = []

        for chunk_extractions, call_result in chunk_results:
            results.extend(chunk_extractions)
            if call_result is not None:
                call_results.append(call_result)

        return results, call_results

    @classmethod
    async def _process_chunk(
        cls, chunk: list[str], offset: int
    ) -> tuple[list[Optional[MessageExtraction]], Optional[LLMCallResult]]:
        try:
            raw_results, call_result = await llm.extract_batch(chunk)
        except Exception as e:
            logger.error(f"LLM extraction failed for chunk at offset {offset}: {e}")
            return [None] * len(chunk), None

        if not isinstance(raw_results, list):
            logger.error(f"LLM returned non-list for chunk at offset {offset}")
            return [None] * len(chunk), call_result

        validated: list[Optional[MessageExtraction]] = []
        for i, raw in enumerate(raw_results):
            if i >= len(chunk):
                break
            original = chunk[i]
            if isinstance(raw, dict):
                extracted = cls._validate_extraction(raw, original)
                validated.append(extracted)
            else:
                logger.warning(f"Non-dict item at index {offset + i}: {raw}")
                validated.append(None)

        # Pad in case LLM returned fewer items than expected
        while len(validated) < len(chunk):
            validated.append(None)

        return validated, call_result

