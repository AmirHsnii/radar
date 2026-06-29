"""
OpenRouterClient — async LLM wrapper for OpenRouter API.

Uses openai.AsyncOpenAI under the hood (OpenRouter is OpenAI-compatible).
All calls go through chat() which:
  • reads retry count and timeout from DB-backed settings at call time
  • retries on rate-limit / server errors with exponential back-off
  • logs token usage and cost via CostTracker
  • returns ChatResult with content + structured usage
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from openai import AsyncOpenAI, APIStatusError, APITimeoutError, RateLimitError
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.core.settings_env import OPENROUTER_API_KEY, OPENROUTER_BASE_URL

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ChatUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float = 0.0


@dataclass
class ChatResult:
    content: str
    usage: ChatUsage
    model: str


# ---------------------------------------------------------------------------
# Retry predicate
# ---------------------------------------------------------------------------

def _is_retryable(exc: BaseException) -> bool:
    """Only retry on transient errors; surface auth / bad-request immediately."""
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, APITimeoutError):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        return True
    return False


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OpenRouterClient:
    """
    Thin async wrapper around openai.AsyncOpenAI pointed at OpenRouter.

    Accepts optional base_url/api_key overrides so each agent can point at
    a different provider (OpenAI, Anthropic, local Ollama, etc.).
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._oa = AsyncOpenAI(
            api_key=api_key or OPENROUTER_API_KEY,
            base_url=base_url or OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": "https://bitpin.ir",
                "X-Title": "Bitpin Radar",
            },
        )

    async def chat(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 512,
        temperature: float = 0.3,
        task_name: str = "unknown",
        news_id: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> ChatResult:
        """
        Send a chat completion request with automatic retry and cost tracking.

        Timeout and max_retries are read from DB settings at call time so
        they can be tuned without restarting workers.
        """
        max_retries = int(await settings.get("ai.max_retries", 3))
        timeout = float(await settings.get("ai.timeout_seconds", 30))

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": timeout,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        attempt_no = 0
        resp = None

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max_retries),
                wait=wait_exponential(multiplier=1, min=2, max=30),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    attempt_no += 1
                    if attempt_no > 1:
                        log.warning(
                            "openrouter.retrying",
                            model=model, attempt=attempt_no, task=task_name,
                        )
                    resp = await self._oa.chat.completions.create(**kwargs)
        except Exception as exc:
            log.error("openrouter.chat_failed", model=model, task=task_name, error=str(exc))
            raise

        content = resp.choices[0].message.content or ""
        raw = resp.usage

        tokens_in  = raw.prompt_tokens     if raw else 0
        tokens_out = raw.completion_tokens if raw else 0
        total      = raw.total_tokens      if raw else 0

        # Lazy import avoids circular dependency at module level
        from app.modules.cost.tracker import cost_tracker
        await cost_tracker.log(
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            task_name=task_name,
            news_id=news_id,
        )

        log.debug(
            "openrouter.chat_done",
            model=model, task=task_name,
            tokens_in=tokens_in, tokens_out=tokens_out,
        )

        return ChatResult(
            content=content,
            usage=ChatUsage(
                prompt_tokens=tokens_in,
                completion_tokens=tokens_out,
                total_tokens=total,
            ),
            model=model,
        )


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_client: OpenRouterClient | None = None


def get_client() -> OpenRouterClient:
    """Return the default global client (uses env-var credentials)."""
    global _client
    if _client is None:
        _client = OpenRouterClient()
    return _client


async def get_agent_client(agent_name: str) -> OpenRouterClient:
    """
    Return a client configured for a named agent.

    Reads agent.{name}.base_url and agent.{name}.api_key from DB settings.
    Falls back to the global env-var values when either setting is empty.
    A fresh client is created each call; AsyncOpenAI reuses HTTP connections
    internally so this is not expensive.
    """
    base_url = str(await settings.get(f"agent.{agent_name}.base_url", "")).strip()
    api_key  = str(await settings.get(f"agent.{agent_name}.api_key",  "")).strip()
    return OpenRouterClient(
        base_url=base_url or None,
        api_key=api_key or None,
    )


async def get_agent_model(agent_name: str) -> str:
    """
    Return the LLM model name for a named agent.

    Reads agent.{name}.model from DB settings.
    Falls back to ai.fast_model when empty.
    """
    model = str(await settings.get(f"agent.{agent_name}.model", "")).strip()
    if not model:
        model = str(await settings.get("ai.fast_model", "google/gemini-flash-1.5"))
    return model


async def reset_global_client() -> None:
    """Close the module singleton — Celery tasks use a fresh loop each run."""
    global _client
    if _client is None:
        return
    try:
        await _client._oa.close()
    except Exception:
        pass
    _client = None
