from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import ValidationError

from app.config import settings
from app.models.schemas import MessageExtraction
from app.services.llm_service import llm

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
    ) -> list[Optional[MessageExtraction]]:
        if not sms_bodies:
            return []

        results: list[Optional[MessageExtraction]] = []
        # Process in chunks
        chunk_size = settings.batch_size
        for start in range(0, len(sms_bodies), chunk_size):
            chunk = sms_bodies[start : start + chunk_size]
            chunk_results = await cls._process_chunk(chunk, start)
            results.extend(chunk_results)

        return results

    @classmethod
    async def _process_chunk(
        cls, chunk: list[str], offset: int
    ) -> list[Optional[MessageExtraction]]:
        try:
            raw_results = await llm.extract_batch(chunk)
        except Exception as e:
            logger.error(f"LLM extraction failed for chunk at offset {offset}: {e}")
            return [None] * len(chunk)

        if not isinstance(raw_results, list):
            logger.error(f"LLM returned non-list for chunk at offset {offset}")
            return [None] * len(chunk)

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

        # Pad in case LLM returned fewer items
        while len(validated) < len(chunk):
            validated.append(None)

        return validated
