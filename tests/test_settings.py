"""
Unit tests for app.config.Settings.

All DB and Redis I/O is mocked via patching the small protected helpers
(_cache_get, _cache_set, _cache_delete, _db_get, _db_upsert, _db_all),
so no real infrastructure is needed.
"""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings, _cast, _infer_type, SETTING_DEFAULTS
from app.models.settings import AppSetting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(key: str, value: str, value_type: str = "str") -> AppSetting:
    row = AppSetting()
    row.key = key
    row.value = value
    row.value_type = value_type
    row.description = ""
    row.updated_by = None
    row.updated_at = datetime.utcnow()
    return row


def _cached(value: str, value_type: str) -> str:
    return json.dumps({"v": value, "t": value_type})


# ---------------------------------------------------------------------------
# _cast — pure function, no async
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,vtype,expected", [
    ("42",       "int",   42),
    ("-7",       "int",   -7),
    ("3.14",     "float", 3.14),
    ("true",     "bool",  True),
    ("True",     "bool",  True),
    ("1",        "bool",  True),
    ("yes",      "bool",  True),
    ("false",    "bool",  False),
    ("False",    "bool",  False),
    ("0",        "bool",  False),
    ("no",       "bool",  False),
    ('{"a":1}',  "json",  {"a": 1}),
    ('[1,2,3]',  "json",  [1, 2, 3]),
    ("hello",    "str",   "hello"),
    ("42",       "str",   "42"),
    ("42",       "unknown", "42"),  # unknown type falls back to str
])
def test_cast(raw, vtype, expected):
    assert _cast(raw, vtype) == expected


# ---------------------------------------------------------------------------
# _infer_type — pure function, no async
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected_type,expected_str", [
    (True,        "bool",  "true"),
    (False,       "bool",  "false"),
    (42,          "int",   "42"),
    (3.14,        "float", "3.14"),
    ({"k": "v"}, "json",  '{"k": "v"}'),
    ([1, 2],      "json",  "[1, 2]"),
    ("hello",     "str",   "hello"),
])
def test_infer_type(value, expected_type, expected_str):
    vtype, str_val = _infer_type(value)
    assert vtype == expected_type
    # For json, compare parsed to handle key ordering
    if expected_type == "json":
        assert json.loads(str_val) == json.loads(expected_str)
    else:
        assert str_val == expected_str


def test_infer_type_bool_before_int():
    # bool is subclass of int in Python — must be handled first
    vtype, _ = _infer_type(True)
    assert vtype == "bool"


# ---------------------------------------------------------------------------
# Settings.get — async
# ---------------------------------------------------------------------------

@pytest.fixture
def svc() -> Settings:
    return Settings(cache_ttl=300)


@pytest.mark.asyncio
async def test_get_cache_hit_returns_cast_value(svc):
    svc._cache_get = AsyncMock(return_value=_cached("42", "int"))
    svc._db_get = AsyncMock()

    result = await svc.get("ai.batch_size")

    assert result == 42
    svc._db_get.assert_not_called()


@pytest.mark.asyncio
async def test_get_cache_miss_hits_db_and_populates_cache(svc):
    svc._cache_get = AsyncMock(return_value=None)
    svc._db_get = AsyncMock(return_value=_row("ai.batch_size", "5", "int"))
    svc._cache_set = AsyncMock()

    result = await svc.get("ai.batch_size")

    assert result == 5
    svc._cache_set.assert_awaited_once()
    payload = json.loads(svc._cache_set.call_args[0][1])
    assert payload == {"v": "5", "t": "int"}


@pytest.mark.asyncio
async def test_get_returns_default_when_missing(svc):
    svc._cache_get = AsyncMock(return_value=None)
    svc._db_get = AsyncMock(return_value=None)

    result = await svc.get("nonexistent.key", "fallback")

    assert result == "fallback"


@pytest.mark.asyncio
async def test_get_default_is_none_when_not_provided(svc):
    svc._cache_get = AsyncMock(return_value=None)
    svc._db_get = AsyncMock(return_value=None)

    result = await svc.get("nonexistent.key")

    assert result is None


@pytest.mark.asyncio
async def test_get_int_from_db(svc):
    svc._cache_get = AsyncMock(return_value=None)
    svc._db_get = AsyncMock(return_value=_row("crawler.poll_interval_minutes", "15", "int"))
    svc._cache_set = AsyncMock()

    assert await svc.get("crawler.poll_interval_minutes") == 15


@pytest.mark.asyncio
async def test_get_float_from_db(svc):
    svc._cache_get = AsyncMock(return_value=None)
    svc._db_get = AsyncMock(return_value=_row("classifier.category_threshold", "0.72", "float"))
    svc._cache_set = AsyncMock()

    assert await svc.get("classifier.category_threshold") == pytest.approx(0.72)


@pytest.mark.asyncio
async def test_get_bool_true_from_db(svc):
    svc._cache_get = AsyncMock(return_value=None)
    svc._db_get = AsyncMock(return_value=_row("publisher.auto_publish", "true", "bool"))
    svc._cache_set = AsyncMock()

    assert await svc.get("publisher.auto_publish") is True


@pytest.mark.asyncio
async def test_get_bool_false_from_db(svc):
    svc._cache_get = AsyncMock(return_value=None)
    svc._db_get = AsyncMock(return_value=_row("publisher.auto_publish", "false", "bool"))
    svc._cache_set = AsyncMock()

    assert await svc.get("publisher.auto_publish") is False


@pytest.mark.asyncio
async def test_get_json_from_db(svc):
    svc._cache_get = AsyncMock(return_value=None)
    svc._db_get = AsyncMock(return_value=_row("some.json_key", '["a","b"]', "json"))
    svc._cache_set = AsyncMock()

    assert await svc.get("some.json_key") == ["a", "b"]


@pytest.mark.asyncio
async def test_get_does_not_cache_on_db_miss(svc):
    svc._cache_get = AsyncMock(return_value=None)
    svc._db_get = AsyncMock(return_value=None)
    svc._cache_set = AsyncMock()

    await svc.get("missing.key", "default")

    svc._cache_set.assert_not_called()


# ---------------------------------------------------------------------------
# Settings.set — async
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_infers_int_type(svc):
    svc._db_upsert = AsyncMock(return_value=_row("ai.batch_size", "10", "int"))
    svc._cache_delete = AsyncMock()

    await svc.set("ai.batch_size", 10, updated_by="admin")

    call_kwargs = svc._db_upsert.call_args
    assert call_kwargs[1]["value_type"] == "int"
    assert call_kwargs[1]["value"] == "10"
    assert call_kwargs[1]["updated_by"] == "admin"


@pytest.mark.asyncio
async def test_set_infers_bool_type(svc):
    svc._db_upsert = AsyncMock(return_value=_row("publisher.auto_publish", "true", "bool"))
    svc._cache_delete = AsyncMock()

    await svc.set("publisher.auto_publish", True)

    call_kwargs = svc._db_upsert.call_args
    assert call_kwargs[1]["value_type"] == "bool"
    assert call_kwargs[1]["value"] == "true"


@pytest.mark.asyncio
async def test_set_accepts_explicit_value_type(svc):
    svc._db_upsert = AsyncMock(return_value=_row("some.key", "42", "int"))
    svc._cache_delete = AsyncMock()

    await svc.set("some.key", "42", value_type="int")

    assert svc._db_upsert.call_args[1]["value_type"] == "int"


@pytest.mark.asyncio
async def test_set_invalidates_cache(svc):
    svc._db_upsert = AsyncMock(return_value=_row("ai.batch_size", "10", "int"))
    svc._cache_delete = AsyncMock()

    await svc.set("ai.batch_size", 10)

    svc._cache_delete.assert_awaited_once_with("ai.batch_size")


@pytest.mark.asyncio
async def test_set_default_updated_by_is_system(svc):
    svc._db_upsert = AsyncMock(return_value=_row("x", "v", "str"))
    svc._cache_delete = AsyncMock()

    await svc.set("x", "v")

    assert svc._db_upsert.call_args[1]["updated_by"] == "system"


# ---------------------------------------------------------------------------
# Settings.refresh — async
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_deletes_cache_key(svc):
    svc._cache_delete = AsyncMock()

    await svc.refresh("ai.fast_model")

    svc._cache_delete.assert_awaited_once_with("ai.fast_model")


# ---------------------------------------------------------------------------
# Settings.prefetch_all — async
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prefetch_all_caches_all_rows(svc):
    rows = [
        _row("ai.batch_size", "5", "int"),
        _row("ai.fast_model", "google/gemini-flash-1.5", "str"),
        _row("publisher.auto_publish", "false", "bool"),
    ]
    svc._db_all = AsyncMock(return_value=rows)
    svc._cache_set = AsyncMock()

    count = await svc.prefetch_all()

    assert count == 3
    assert svc._cache_set.await_count == 3

    # Verify each cache payload has v + t keys
    for call in svc._cache_set.await_args_list:
        payload = json.loads(call[0][1])
        assert "v" in payload and "t" in payload


@pytest.mark.asyncio
async def test_prefetch_all_returns_zero_for_empty_db(svc):
    svc._db_all = AsyncMock(return_value=[])
    svc._cache_set = AsyncMock()

    count = await svc.prefetch_all()

    assert count == 0
    svc._cache_set.assert_not_called()


# ---------------------------------------------------------------------------
# SETTING_DEFAULTS — contract tests
# ---------------------------------------------------------------------------

def test_all_defaults_have_valid_type():
    for key, (_, vtype, _) in SETTING_DEFAULTS.items():
        assert vtype in {"str", "int", "float", "bool", "json"}, (
            f"{key}: unknown type '{vtype}'"
        )


def test_all_defaults_have_description():
    for key, (_, _, desc) in SETTING_DEFAULTS.items():
        assert desc, f"{key}: description is empty"


def test_all_defaults_are_castable():
    for key, (default, vtype, _) in SETTING_DEFAULTS.items():
        try:
            _cast(default, vtype)
        except Exception as exc:
            pytest.fail(f"{key}: default '{default}' cannot be cast as {vtype}: {exc}")


def test_defaults_cover_all_known_categories():
    categories = {k.split(".")[0] for k in SETTING_DEFAULTS}
    assert "crawler" in categories
    assert "ai" in categories
    assert "classifier" in categories
    assert "publisher" in categories
    assert "cost" in categories
