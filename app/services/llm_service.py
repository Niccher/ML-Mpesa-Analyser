from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, NamedTuple, Optional

import httpx

from app.config import settings
from app.services.prompt_manager import resolve as resolve_prompt

logger = logging.getLogger(__name__)


class LLMCallResult(NamedTuple):
    """Structured result from a single LLM HTTP call — includes the text
    content plus telemetry data used for audit logging."""
    content: str
    latency_ms: int
    prompt_tokens: Optional[int]   # None when provider doesn't expose usage
    reply_tokens: Optional[int]
    model: str
    provider: str
    used_fallback: bool


class LLMService:
    def __init__(self):
        self.provider = settings.llm_provider
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self.max_tokens = settings.llm_max_tokens
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=600.0)
        return self._client

    async def _call_llm(
        self,
        messages: list[dict],
        response_format: Optional[str] = None,
        use_fallback: bool = False,
    ) -> LLMCallResult:
        """Call the LLM and return a LLMCallResult with content + telemetry.

        Retries up to max_retries with exponential back-off. Transparently
        falls back to the configured fallback provider on total failure.
        """
        client = await self._get_client()

        if use_fallback and settings.llm_fallback_enabled:
            provider    = settings.llm_fallback_provider
            url_base    = settings.llm_fallback_base_url.rstrip("/")
            model       = settings.llm_fallback_model
            api_key     = settings.llm_fallback_api_key
            max_tokens  = settings.llm_max_tokens
            temperature = settings.llm_temperature
            max_retries = 2
        elif settings.llm_engine == "external":
            provider    = settings.llm_external_provider
            url_base    = settings.llm_external_base_url.rstrip("/")
            model       = settings.llm_external_model
            api_key     = settings.llm_external_api_key
            max_tokens  = settings.llm_external_max_tokens
            temperature = settings.llm_external_temperature
            max_retries = settings.external_max_retries or 3
        else:
            provider    = settings.llm_provider
            url_base    = settings.llm_base_url.rstrip("/")
            model       = settings.llm_model
            api_key     = settings.llm_api_key
            max_tokens  = settings.llm_max_tokens
            temperature = settings.llm_temperature
            max_retries = settings.max_retries or 3

        last_exception = None
        for attempt in range(1, max_retries + 1):
            t_start = time.perf_counter()
            try:
                # ── Google Gemini: native generateContent API ────────────────────
                if provider == "gemini":
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                    gemini_contents = []
                    system_parts = []
                    for msg in messages:
                        role    = msg.get("role", "user")
                        content = msg.get("content", "")
                        if role == "system":
                            system_parts.append({"text": content})
                        elif role == "assistant":
                            gemini_contents.append({"role": "model", "parts": [{"text": content}]})
                        else:
                            gemini_contents.append({"role": "user", "parts": [{"text": content}]})

                    body: dict[str, Any] = {
                        "contents": gemini_contents,
                        "generationConfig": {
                            "maxOutputTokens": max_tokens,
                            "temperature": temperature,
                        },
                    }
                    if system_parts:
                        body["systemInstruction"] = {"parts": system_parts}
                    if response_format == "json_object":
                        body["generationConfig"]["responseMimeType"] = "application/json"

                    resp = await client.post(
                        url,
                        headers={
                            "Content-Type": "application/json",
                            "X-goog-api-key": api_key,
                        },
                        json=body,
                    )
                    resp.raise_for_status()
                    latency_ms = int((time.perf_counter() - t_start) * 1000)

                    data = resp.json()
                    content = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if content.startswith("```"):
                        lines = content.splitlines()
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].strip() == "```":
                            lines = lines[:-1]
                        content = "\n".join(lines).strip()

                    # Gemini exposes token counts in usageMetadata
                    usage = data.get("usageMetadata", {})
                    prompt_tokens = usage.get("promptTokenCount")
                    reply_tokens  = usage.get("candidatesTokenCount")

                    return LLMCallResult(
                        content=content,
                        latency_ms=latency_ms,
                        prompt_tokens=prompt_tokens,
                        reply_tokens=reply_tokens,
                        model=model,
                        provider=provider,
                        used_fallback=use_fallback,
                    )

                # ── All OpenAI-compat providers ──────────────────────────────────
                url = f"{url_base}/chat/completions"
                headers: dict[str, str] = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                body = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                if response_format == "json_object":
                    body["response_format"] = {"type": "json_object"}

                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                latency_ms = int((time.perf_counter() - t_start) * 1000)

                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    lines = content.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()

                # OpenAI-compat usage block
                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens")
                reply_tokens  = usage.get("completion_tokens")

                return LLMCallResult(
                    content=content,
                    latency_ms=latency_ms,
                    prompt_tokens=prompt_tokens,
                    reply_tokens=reply_tokens,
                    model=model,
                    provider=provider,
                    used_fallback=use_fallback,
                )

            except Exception as e:
                last_exception = e
                logger.warning(f"LLM call attempt {attempt}/{max_retries} failed for model {model}: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(1.5 * attempt)

        logger.error(f"All {max_retries} attempts failed for model {model}: {last_exception}")
        if not use_fallback and settings.llm_fallback_enabled:
            logger.warning(f"Retrying with fallback provider model: {settings.llm_fallback_model}")
            return await self._call_llm(messages, response_format, use_fallback=True)

        raise last_exception

    async def classify_sender(self, sender: str, sms_messages: list[str]) -> tuple[dict, LLMCallResult]:
        """Returns (parsed_dict, call_result) so callers can log telemetry."""
        sample = sms_messages[:10]
        formatted = "\n---\n".join(f"[{i+1}] {m[:300]}" for i, m in enumerate(sample))

        prompt = await resolve_prompt(
            "classify_sender",
            sender=sender,
            sms_messages=formatted,
        )

        call_result = await self._call_llm(
            [{"role": "user", "content": prompt}],
            response_format="json_object",
        )
        return json.loads(call_result.content), call_result

    async def extract_batch(self, sms_bodies: list[str]) -> tuple[list[dict], LLMCallResult]:
        """Returns (parsed_list, call_result) so callers can log telemetry."""
        items = "\n".join(
            f"{i} | {body[:500]}" for i, body in enumerate(sms_bodies)
        )

        prompt = await resolve_prompt(
            "extract_batch",
            messages_list=items,
        )

        call_result = await self._call_llm(
            [{"role": "user", "content": prompt}],
        )
        return json.loads(call_result.content), call_result

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


llm = LLMService()

