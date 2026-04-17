"""Ollama LLM client — calls the OpenAI-compatible API at localhost:11434."""
from __future__ import annotations

import asyncio
import logging

from openai import AsyncOpenAI, APIConnectionError, APIStatusError

from utils.config import config
from utils.rate_limiter import LIMITERS

log = logging.getLogger(__name__)

_limiter = LIMITERS["ollama"]
_semaphore = asyncio.Semaphore(2)  # max 2 concurrent LLM calls to avoid OOM

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=config.ollama_api_url,
            api_key="ollama",  # Ollama accepts any non-empty string
            timeout=300.0,
            max_retries=0,  # we handle retries ourselves
        )
    return _client


async def complete(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 65536,
    temperature: float = 0.3,
    retries: int = 3,
) -> str:
    """Send a chat completion request to Ollama and return the response text."""
    await _limiter.acquire()

    for attempt in range(retries):
        try:
            async with _semaphore:
                response = await _get_client().chat.completions.create(
                    model=config.ollama_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    extra_body={"num_ctx": 65536},
                )
            return response.choices[0].message.content or ""
        except APIConnectionError as e:
            wait = 2 ** attempt
            log.warning("[LLM] Connection error (attempt %d/%d): %s. Retrying in %ds",
                        attempt + 1, retries, e, wait)
            await asyncio.sleep(wait)
        except APIStatusError as e:
            log.error("[LLM] API status error %d: %s", e.status_code, e.message)
            return f"[LLM error: {e.status_code}]"
        except Exception as e:
            log.error("[LLM] Unexpected error: %s", e)
            return f"[LLM error: {e}]"

    return "[LLM unavailable — Ollama did not respond after retries]"


async def ping() -> bool:
    """Test connectivity to Ollama. Returns True if reachable."""
    try:
        models = await _get_client().models.list()
        model_ids = [m.id for m in models.data]
        log.info("[LLM] Ollama reachable. Available models: %s", model_ids)
        return True
    except Exception as e:
        log.warning("[LLM] Ollama not reachable: %s", e)
        return False
