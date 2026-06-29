"""
Unit tests for OpenRouterClient and CostTracker.

All external I/O (OpenAI SDK, Redis, DB, HTTP) is mocked.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.openrouter import (
    ChatResult,
    ChatUsage,
    OpenRouterClient,
    _is_retryable,
    get_client,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(max_retries=3, timeout=30):
    mock = MagicMock()
    async def _get(key, default=None):
        return {
            "ai.max_retries": max_retries,
            "ai.timeout_seconds": timeout,
        }.get(key, default)
    mock.get = _get
    return mock


def _make_completion(content="Test content", prompt_tokens=100, completion_tokens=50):
    """Build a mock openai ChatCompletion response."""
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = prompt_tokens + completion_tokens

    choice = MagicMock()
    choice.message.content = content

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


@pytest.fixture
def client() -> OpenRouterClient:
    return OpenRouterClient()


# ===========================================================================
# _is_retryable
# ===========================================================================

def test_retryable_rate_limit():
    from openai import RateLimitError
    exc = RateLimitError("rate limited", response=MagicMock(), body={})
    assert _is_retryable(exc) is True


def test_retryable_timeout():
    from openai import APITimeoutError
    exc = APITimeoutError(request=MagicMock())
    assert _is_retryable(exc) is True


def test_retryable_server_error():
    from openai import APIStatusError
    exc = APIStatusError("server error", response=MagicMock(status_code=503), body={})
    assert _is_retryable(exc) is True


def test_not_retryable_auth_error():
    from openai import APIStatusError
    exc = APIStatusError("unauthorized", response=MagicMock(status_code=401), body={})
    assert _is_retryable(exc) is False


def test_not_retryable_bad_request():
    from openai import APIStatusError
    exc = APIStatusError("bad request", response=MagicMock(status_code=400), body={})
    assert _is_retryable(exc) is False


def test_not_retryable_generic_exception():
    assert _is_retryable(ValueError("bad input")) is False


# ===========================================================================
# OpenRouterClient.chat — happy path
# ===========================================================================

@pytest.mark.asyncio
async def test_chat_returns_chat_result(client):
    resp = _make_completion("Bitcoin ATH reached", 200, 80)

    mock_oa = AsyncMock()
    mock_oa.chat.completions.create = AsyncMock(return_value=resp)
    client._oa = mock_oa

    mock_cost = AsyncMock()

    with patch("app.core.openrouter.settings", _make_settings()), \
         patch("app.modules.cost.tracker.cost_tracker", mock_cost):
        result = await client.chat(
            model="google/gemini-flash-1.5",
            messages=[{"role": "user", "content": "Summarize"}],
        )

    assert isinstance(result, ChatResult)
    assert result.content == "Bitcoin ATH reached"
    assert result.model == "google/gemini-flash-1.5"
    assert isinstance(result.usage, ChatUsage)
    assert result.usage.prompt_tokens == 200
    assert result.usage.completion_tokens == 80
    assert result.usage.total_tokens == 280


@pytest.mark.asyncio
async def test_chat_passes_all_params(client):
    resp = _make_completion()
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return resp

    client._oa = MagicMock()
    client._oa.chat.completions.create = fake_create

    with patch("app.core.openrouter.settings", _make_settings(timeout=45)), \
         patch("app.modules.cost.tracker.cost_tracker", AsyncMock()):
        await client.chat(
            model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=256,
            temperature=0.7,
            response_format={"type": "json_object"},
        )

    assert captured["model"] == "openai/gpt-4o-mini"
    assert captured["max_tokens"] == 256
    assert captured["temperature"] == 0.7
    assert captured["timeout"] == 45
    assert captured["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_chat_omits_response_format_when_none(client):
    resp = _make_completion()
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return resp

    client._oa = MagicMock()
    client._oa.chat.completions.create = fake_create

    with patch("app.core.openrouter.settings", _make_settings()), \
         patch("app.modules.cost.tracker.cost_tracker", AsyncMock()):
        await client.chat(
            model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            response_format=None,
        )

    assert "response_format" not in captured


@pytest.mark.asyncio
async def test_chat_calls_cost_tracker(client):
    resp = _make_completion("result", prompt_tokens=150, completion_tokens=60)
    client._oa = MagicMock()
    client._oa.chat.completions.create = AsyncMock(return_value=resp)

    mock_tracker = MagicMock()
    mock_tracker.log = AsyncMock()

    with patch("app.core.openrouter.settings", _make_settings()), \
         patch("app.modules.cost.tracker.cost_tracker", mock_tracker):
        await client.chat(
            model="gpt-4o",
            messages=[],
            task_name="summarize",
            news_id=42,
        )

    mock_tracker.log.assert_awaited_once_with(
        model="gpt-4o",
        tokens_in=150,
        tokens_out=60,
        task_name="summarize",
        news_id=42,
    )


@pytest.mark.asyncio
async def test_chat_timeout_from_settings(client):
    resp = _make_completion()
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return resp

    client._oa = MagicMock()
    client._oa.chat.completions.create = fake_create

    with patch("app.core.openrouter.settings", _make_settings(timeout=99)), \
         patch("app.modules.cost.tracker.cost_tracker", AsyncMock()):
        await client.chat(model="m", messages=[])

    assert captured["timeout"] == 99


# ===========================================================================
# Retry behaviour
# ===========================================================================

@pytest.mark.asyncio
async def test_chat_retries_on_rate_limit(client):
    from openai import RateLimitError

    call_count = 0

    async def flaky_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RateLimitError("slow down", response=MagicMock(), body={})
        return _make_completion("ok after retry")

    client._oa = MagicMock()
    client._oa.chat.completions.create = flaky_create

    with patch("app.core.openrouter.settings", _make_settings(max_retries=3)), \
         patch("app.modules.cost.tracker.cost_tracker", AsyncMock()), \
         patch("tenacity.nap.time"):  # skip actual sleep in tests
        result = await client.chat(model="m", messages=[])

    assert call_count == 3
    assert result.content == "ok after retry"


@pytest.mark.asyncio
async def test_chat_no_retry_on_auth_error(client):
    from openai import APIStatusError

    call_count = 0

    async def always_401(**kwargs):
        nonlocal call_count
        call_count += 1
        raise APIStatusError("unauthorized", response=MagicMock(status_code=401), body={})

    client._oa = MagicMock()
    client._oa.chat.completions.create = always_401

    with patch("app.core.openrouter.settings", _make_settings(max_retries=3)), \
         patch("app.modules.cost.tracker.cost_tracker", AsyncMock()):
        with pytest.raises(APIStatusError):
            await client.chat(model="m", messages=[])

    assert call_count == 1  # no retry


@pytest.mark.asyncio
async def test_chat_raises_after_max_retries(client):
    from openai import RateLimitError

    async def always_rate_limit(**kwargs):
        raise RateLimitError("forever", response=MagicMock(), body={})

    client._oa = MagicMock()
    client._oa.chat.completions.create = always_rate_limit

    with patch("app.core.openrouter.settings", _make_settings(max_retries=2)), \
         patch("app.modules.cost.tracker.cost_tracker", AsyncMock()), \
         patch("tenacity.nap.time"):
        with pytest.raises(RateLimitError):
            await client.chat(model="m", messages=[])


# ===========================================================================
# get_client singleton
# ===========================================================================

def test_get_client_returns_same_instance():
    import app.core.openrouter as mod
    mod._client = None   # reset

    c1 = get_client()
    c2 = get_client()
    assert c1 is c2


# ===========================================================================
# CostTracker
# ===========================================================================

from app.modules.cost.tracker import CostTracker, _FALLBACK, _DEFAULT_PRICING


@pytest.fixture
def tracker() -> CostTracker:
    return CostTracker()


def _make_redis(cached_value=None):
    redis = MagicMock()
    redis.get = AsyncMock(return_value=cached_value)
    redis.setex = AsyncMock()
    pipe = MagicMock()
    pipe.setex = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline = MagicMock(return_value=pipe)
    return redis


# ---------------------------------------------------------------------------
# get_model_pricing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pricing_from_redis_cache(tracker):
    import json
    cached = json.dumps({"prompt": 1.5e-7, "completion": 6.0e-7})
    redis = _make_redis(cached_value=cached)

    with patch("app.modules.cost.tracker.get_redis", AsyncMock(return_value=redis)):
        pricing = await tracker.get_model_pricing("openai/gpt-4o-mini")

    assert pricing["prompt"] == pytest.approx(1.5e-7)
    assert pricing["completion"] == pytest.approx(6.0e-7)


@pytest.mark.asyncio
async def test_pricing_fallback_when_redis_and_api_fail(tracker):
    redis = _make_redis(cached_value=None)

    with patch("app.modules.cost.tracker.get_redis", AsyncMock(return_value=redis)), \
         patch.object(tracker, "_fetch_and_cache_all", AsyncMock()):
        pricing = await tracker.get_model_pricing("openai/gpt-4o-mini")

    # After failed fetch, falls back to hardcoded table
    assert pricing == _FALLBACK.get("openai/gpt-4o-mini", _DEFAULT_PRICING)


@pytest.mark.asyncio
async def test_pricing_default_for_unknown_model(tracker):
    redis = _make_redis(cached_value=None)

    with patch("app.modules.cost.tracker.get_redis", AsyncMock(return_value=redis)), \
         patch.object(tracker, "_fetch_and_cache_all", AsyncMock()):
        pricing = await tracker.get_model_pricing("unknown/model-xyz")

    assert pricing == _DEFAULT_PRICING


@pytest.mark.asyncio
async def test_fetch_and_cache_all_calls_openrouter(tracker):
    api_response = {
        "data": [
            {"id": "test/model", "pricing": {"prompt": "0.0000001", "completion": "0.0000002"}},
        ]
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=api_response)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    redis = _make_redis()

    with patch("app.modules.cost.tracker.httpx.AsyncClient", return_value=mock_client):
        await tracker._fetch_and_cache_all(redis)

    redis.pipeline.assert_called_once()
    pipe = redis.pipeline.return_value
    assert pipe.execute.await_count == 1


@pytest.mark.asyncio
async def test_fetch_and_cache_all_handles_api_failure(tracker):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("network error"))

    redis = _make_redis()

    with patch("app.modules.cost.tracker.httpx.AsyncClient", return_value=mock_client):
        # Should not raise — logs the error and sets a short retry TTL
        await tracker._fetch_and_cache_all(redis)

    redis.setex.assert_awaited_once()  # short retry marker


# ---------------------------------------------------------------------------
# log()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_stores_cost_in_db(tracker):
    pricing = {"prompt": 1.0e-6, "completion": 2.0e-6}

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(tracker, "get_model_pricing", AsyncMock(return_value=pricing)), \
         patch("app.modules.cost.tracker.AsyncSessionLocal", return_value=cm):
        await tracker.log(
            model="test/model",
            tokens_in=1000,
            tokens_out=500,
            task_name="translate",
            news_id=7,
        )

    added = session.add.call_args[0][0]
    assert added.model == "test/model"
    assert added.tokens_in == 1000
    assert added.tokens_out == 500
    assert added.task_name == "translate"
    assert added.news_id == 7
    # cost = 1000 * 1e-6 + 500 * 2e-6 = 0.001 + 0.001 = 0.002
    assert added.cost_usd == pytest.approx(0.002)


@pytest.mark.asyncio
async def test_log_zero_tokens_zero_cost(tracker):
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(tracker, "get_model_pricing", AsyncMock(return_value={"prompt": 1e-6, "completion": 1e-6})), \
         patch("app.modules.cost.tracker.AsyncSessionLocal", return_value=cm):
        await tracker.log(model="m", tokens_in=0, tokens_out=0, task_name="t")

    added = session.add.call_args[0][0]
    assert added.cost_usd == 0.0


# ---------------------------------------------------------------------------
# check_budget_alert()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_budget_alert_triggered(tracker):
    def _mock_settings():
        mock = MagicMock()
        async def _get(key, default=None):
            return {"cost.monthly_budget_usd": 100.0, "cost.alert_threshold_pct": 80}.get(key, default)
        mock.get = _get
        return mock

    with patch("app.modules.cost.tracker.settings", _mock_settings()), \
         patch.object(tracker, "monthly", AsyncMock(return_value={
             "total_cost_usd": 85.0,
             "period": "2026-06",
             "tokens_in": 0, "tokens_out": 0, "calls": 0, "by_model": [],
         })):
        result = await tracker.check_budget_alert()

    assert result["alert"] is True
    assert result["spent_pct"] == pytest.approx(85.0)


@pytest.mark.asyncio
async def test_budget_alert_not_triggered(tracker):
    def _mock_settings():
        mock = MagicMock()
        async def _get(key, default=None):
            return {"cost.monthly_budget_usd": 100.0, "cost.alert_threshold_pct": 80}.get(key, default)
        mock.get = _get
        return mock

    with patch("app.modules.cost.tracker.settings", _mock_settings()), \
         patch.object(tracker, "monthly", AsyncMock(return_value={
             "total_cost_usd": 50.0,
             "period": "2026-06",
             "tokens_in": 0, "tokens_out": 0, "calls": 0, "by_model": [],
         })):
        result = await tracker.check_budget_alert()

    assert result["alert"] is False
    assert result["budget_usd"] == 100.0


# ---------------------------------------------------------------------------
# _aggregate / daily / weekly / monthly (DB mocked)
# ---------------------------------------------------------------------------

def _make_aggregate_session(total_cost=10.0, tokens_in=1000, tokens_out=500, calls=5):
    row = MagicMock()
    row.total_cost = total_cost
    row.tokens_in = tokens_in
    row.tokens_out = tokens_out
    row.calls = calls

    result = MagicMock()
    result.one = MagicMock(return_value=row)

    by_model_result = MagicMock()
    by_model_result.__iter__ = MagicMock(return_value=iter([]))

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[result, by_model_result])

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_daily_returns_summary(tracker):
    cm = _make_aggregate_session(total_cost=5.0, calls=10)
    with patch("app.modules.cost.tracker.AsyncSessionLocal", return_value=cm):
        result = await tracker.daily("2026-06-01")

    assert result["period"] == "2026-06-01"
    assert result["total_cost_usd"] == pytest.approx(5.0)
    assert result["calls"] == 10


@pytest.mark.asyncio
async def test_daily_defaults_to_today(tracker):
    from datetime import date as date_type
    today = date_type.today().isoformat()
    cm = _make_aggregate_session()
    with patch("app.modules.cost.tracker.AsyncSessionLocal", return_value=cm):
        result = await tracker.daily()  # no arg

    assert result["period"] == today


@pytest.mark.asyncio
async def test_weekly_returns_7_day_label(tracker):
    cm = _make_aggregate_session()
    with patch("app.modules.cost.tracker.AsyncSessionLocal", return_value=cm):
        result = await tracker.weekly()

    assert "/" in result["period"]  # "YYYY-MM-DD / YYYY-MM-DD"


@pytest.mark.asyncio
async def test_monthly_returns_correct_period(tracker):
    cm = _make_aggregate_session(total_cost=42.0)
    with patch("app.modules.cost.tracker.AsyncSessionLocal", return_value=cm):
        result = await tracker.monthly(year=2026, month=3)

    assert result["period"] == "2026-03"
    assert result["total_cost_usd"] == pytest.approx(42.0)


@pytest.mark.asyncio
async def test_monthly_handles_december(tracker):
    cm = _make_aggregate_session()
    with patch("app.modules.cost.tracker.AsyncSessionLocal", return_value=cm):
        result = await tracker.monthly(year=2026, month=12)

    assert result["period"] == "2026-12"
