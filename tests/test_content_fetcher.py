"""
Unit tests for ContentFetcher and WhitelistFilter.

All external I/O (HTTP, DB, Redis) is mocked.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.crawler.content_fetcher import ContentFetcher, _clean, fetch_content
from app.modules.crawler.whitelist import (
    WhitelistFilter,
    passes_whitelist,
    whitelist_filter,
)


# ===========================================================================
# _clean() — pure helper, no mocking needed
# ===========================================================================

class TestClean:
    def test_strips_edges(self):
        assert _clean("  hello  ") == "hello"

    def test_collapses_spaces_and_tabs(self):
        assert _clean("a  b\t\tc") == "a b c"

    def test_collapses_multiple_newlines(self):
        text = "para1\n\n\n\npara2"
        assert _clean(text) == "para1\n\npara2"

    def test_two_newlines_unchanged(self):
        assert _clean("a\n\nb") == "a\n\nb"

    def test_single_newline_unchanged(self):
        assert _clean("a\nb") == "a\nb"

    def test_empty_string(self):
        assert _clean("") == ""


# ===========================================================================
# ContentFetcher.fetch — happy paths and failure modes
# ===========================================================================

@pytest.fixture
def fetcher() -> ContentFetcher:
    return ContentFetcher()


def _patch_settings(timeout=10, max_len=5000, ua="TestBot/1.0"):
    mock = MagicMock()

    async def _get(key, default=None):
        return {
            "crawler.request_timeout_seconds": timeout,
            "crawler.max_content_length": max_len,
            "crawler.user_agent": ua,
        }.get(key, default)

    mock.get = _get
    return mock


@pytest.mark.asyncio
async def test_fetch_trafilatura_success(fetcher):
    fetcher._download = AsyncMock(return_value="<html>article</html>")
    fetcher._extract_trafilatura = AsyncMock(return_value="Full article text.")
    fetcher._extract_newspaper = AsyncMock(return_value="Should not be called")

    with patch("app.modules.crawler.content_fetcher.settings", _patch_settings()):
        result = await fetcher.fetch("https://example.com/article")

    assert result == "Full article text."
    fetcher._extract_newspaper.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_falls_back_to_newspaper(fetcher):
    fetcher._download = AsyncMock(return_value="<html>article</html>")
    fetcher._extract_trafilatura = AsyncMock(return_value="")   # trafilatura fails
    fetcher._extract_newspaper = AsyncMock(return_value="Newspaper text.")

    with patch("app.modules.crawler.content_fetcher.settings", _patch_settings()):
        result = await fetcher.fetch("https://example.com/article")

    assert result == "Newspaper text."


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_both_fail(fetcher):
    fetcher._download = AsyncMock(return_value="<html>article</html>")
    fetcher._extract_trafilatura = AsyncMock(return_value="")
    fetcher._extract_newspaper = AsyncMock(return_value="")

    with patch("app.modules.crawler.content_fetcher.settings", _patch_settings()):
        result = await fetcher.fetch("https://example.com/article")

    assert result == ""


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_download_fails(fetcher):
    fetcher._download = AsyncMock(return_value="")

    with patch("app.modules.crawler.content_fetcher.settings", _patch_settings()):
        result = await fetcher.fetch("https://example.com/article")

    assert result == ""


@pytest.mark.asyncio
async def test_fetch_truncates_to_max_length(fetcher):
    long_text = "a" * 10_000
    fetcher._download = AsyncMock(return_value="<html/>")
    fetcher._extract_trafilatura = AsyncMock(return_value=long_text)

    with patch("app.modules.crawler.content_fetcher.settings", _patch_settings(max_len=100)):
        result = await fetcher.fetch("https://example.com/article")

    assert len(result) == 100


@pytest.mark.asyncio
async def test_fetch_normalizes_whitespace(fetcher):
    raw = "  Bitcoin   rises  \n\n\n\n to  ATH  "
    fetcher._download = AsyncMock(return_value="<html/>")
    fetcher._extract_trafilatura = AsyncMock(return_value=raw)

    with patch("app.modules.crawler.content_fetcher.settings", _patch_settings()):
        result = await fetcher.fetch("https://example.com/article")

    assert "  " not in result          # no double spaces
    assert "bitcoin" in result.lower()  # content intact
    assert result.startswith("Bitcoin") # leading whitespace stripped


@pytest.mark.asyncio
async def test_fetch_uses_timeout_from_settings(fetcher):
    captured: dict = {}

    async def fake_download(url, *, timeout, ua):
        captured["timeout"] = timeout
        return ""

    fetcher._download = fake_download

    with patch("app.modules.crawler.content_fetcher.settings", _patch_settings(timeout=42)):
        await fetcher.fetch("https://example.com")

    assert captured["timeout"] == 42


@pytest.mark.asyncio
async def test_fetch_uses_ua_from_settings(fetcher):
    captured: dict = {}

    async def fake_download(url, *, timeout, ua):
        captured["ua"] = ua
        return ""

    fetcher._download = fake_download

    with patch("app.modules.crawler.content_fetcher.settings", _patch_settings(ua="CustomBot/2.0")):
        await fetcher.fetch("https://example.com")

    assert captured["ua"] == "CustomBot/2.0"


# ---------------------------------------------------------------------------
# _download — network-level error handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_returns_empty_on_http_error(fetcher):
    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock()
    )
    mock_response.text = "error page"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("app.modules.crawler.content_fetcher.httpx.AsyncClient", return_value=mock_client):
        result = await fetcher._download("https://example.com", timeout=5, ua="Bot")

    assert result == ""


@pytest.mark.asyncio
async def test_download_returns_empty_on_connection_error(fetcher):
    import httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

    with patch("app.modules.crawler.content_fetcher.httpx.AsyncClient", return_value=mock_client):
        result = await fetcher._download("https://example.com", timeout=5, ua="Bot")

    assert result == ""


# ---------------------------------------------------------------------------
# _extract_trafilatura — exception safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_trafilatura_returns_empty_on_exception(fetcher):
    with patch("app.modules.crawler.content_fetcher.trafilatura.extract",
               side_effect=RuntimeError("parse error")):
        result = await fetcher._extract_trafilatura("<html>bad</html>")

    assert result == ""


# ---------------------------------------------------------------------------
# _extract_newspaper — exception safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_newspaper_returns_empty_on_exception(fetcher):
    with patch.object(fetcher, "_parse_newspaper", side_effect=ImportError("no newspaper")):
        result = await fetcher._extract_newspaper("https://x.com", "<html/>")

    assert result == ""


# ---------------------------------------------------------------------------
# Module-level fetch_content wrapper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_content_delegates_to_singleton():
    with patch("app.modules.crawler.content_fetcher.content_fetcher") as mock_cf:
        mock_cf.fetch = AsyncMock(return_value="article text")
        result = await fetch_content("https://example.com")

    assert result == "article text"
    mock_cf.fetch.assert_awaited_once_with("https://example.com")


# ===========================================================================
# WhitelistFilter
# ===========================================================================

@pytest.fixture
def wf() -> WhitelistFilter:
    f = WhitelistFilter()
    return f


def _mock_settings_for_whitelist(fa_keywords=None, en_keywords=None):
    mock = MagicMock()

    async def _get(key, default=None):
        if key == "crawler.whitelist_keywords_fa":
            return fa_keywords
        if key == "crawler.whitelist_keywords_en":
            return en_keywords
        if key == "crawler.whitelist_keywords":
            return fa_keywords
        return default

    mock.get = _get
    return mock


# ---------------------------------------------------------------------------
# passes() — async, lazy-loads keywords
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_passes_crypto_keyword(wf):
    with patch("app.modules.crawler.whitelist.settings", _mock_settings_for_whitelist(None)):
        assert await wf.passes("Bitcoin rises to new ATH", "en") is True


@pytest.mark.asyncio
async def test_passes_persian_crypto(wf):
    with patch("app.modules.crawler.whitelist.settings", _mock_settings_for_whitelist(None)):
        assert await wf.passes("بیتکوین امروز رکورد زد", "fa") is True


@pytest.mark.asyncio
async def test_passes_rejects_irrelevant(wf):
    with patch("app.modules.crawler.whitelist.settings", _mock_settings_for_whitelist(None)):
        assert await wf.passes("Today's weather forecast for Tehran", "fa") is False


@pytest.mark.asyncio
async def test_passes_empty_title(wf):
    with patch("app.modules.crawler.whitelist.settings", _mock_settings_for_whitelist(None)):
        assert await wf.passes("", "fa") is False


@pytest.mark.asyncio
async def test_passes_normalizes_zwnj(wf):
    with patch("app.modules.crawler.whitelist.settings", _mock_settings_for_whitelist(None)):
        assert await wf.passes("بیت‌کوین به اوج رسید", "fa") is True


@pytest.mark.asyncio
async def test_passes_case_insensitive(wf):
    custom = ["bitcoin"]
    with patch("app.modules.crawler.whitelist.settings",
               _mock_settings_for_whitelist(fa_keywords=custom)):
        assert await wf.passes("BITCOIN IS RISING", "fa") is True


# ---------------------------------------------------------------------------
# Keywords from settings override defaults
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_passes_uses_custom_keywords(wf):
    custom = ["altseason", "degen"]
    with patch("app.modules.crawler.whitelist.settings",
               _mock_settings_for_whitelist(fa_keywords=custom)):
        assert await wf.passes("altseason is here", "fa") is True
        assert await wf.passes("Bitcoin rises", "fa") is False


@pytest.mark.asyncio
async def test_passes_custom_keywords_as_json_string(wf):
    import json
    json_str = json.dumps(["plasma", "zk-rollup"])
    with patch("app.modules.crawler.whitelist.settings",
               _mock_settings_for_whitelist(fa_keywords=json_str)):
        assert await wf.passes("plasma network launched", "fa") is True


# ---------------------------------------------------------------------------
# reload() clears and re-fetches keywords
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reload_returns_keyword_count(wf):
    custom = ["sol", "ada", "dot"]
    with patch("app.modules.crawler.whitelist.settings",
               _mock_settings_for_whitelist(fa_keywords=custom)):
        fa_count, en_count = await wf.reload()

    assert fa_count == 3
    assert en_count == 0


@pytest.mark.asyncio
async def test_reload_updates_keywords(wf):
    # Load with default (None → built-in list)
    with patch("app.modules.crawler.whitelist.settings",
               _mock_settings_for_whitelist(None)):
        await wf.passes("trigger load", "fa")

    assert wf._keywords_fa is not None
    original_len = len(wf._keywords_fa)

    with patch("app.modules.crawler.whitelist.settings",
               _mock_settings_for_whitelist(fa_keywords=["only_this"])):
        await wf.reload()

    assert wf._keywords_fa == ["only_this"]
    assert len(wf._keywords_fa) < original_len


@pytest.mark.asyncio
async def test_reload_falls_back_to_defaults_on_none(wf):
    with patch("app.modules.crawler.whitelist.settings",
               _mock_settings_for_whitelist(None)):
        fa_count, _ = await wf.reload()

    from app.modules.crawler.whitelist import _DEFAULT_FA_KEYWORDS
    assert fa_count == len(_DEFAULT_FA_KEYWORDS)


# ---------------------------------------------------------------------------
# passes_sync() — synchronous, no I/O
# ---------------------------------------------------------------------------

def test_passes_sync_uses_defaults_when_not_loaded():
    f = WhitelistFilter()
    assert f.passes_sync("بیتکوین drops 10%", "fa") is True
    assert f.passes_sync("Sports news today", "fa") is False
    assert f.passes_sync("Sports news today", "en") is True


def test_passes_sync_uses_loaded_keywords():
    f = WhitelistFilter()
    f._keywords_fa = ["testcoin"]
    assert f.passes_sync("testcoin launches mainnet", "fa") is True
    assert f.passes_sync("bitcoin today", "fa") is False


# ---------------------------------------------------------------------------
# Module-level passes_whitelist (backward-compat)
# ---------------------------------------------------------------------------

def test_module_passes_whitelist_crypto():
    assert passes_whitelist("Ethereum merge is complete", "en") is True


def test_module_passes_whitelist_fa_crypto():
    assert passes_whitelist("ارز دیجیتال رکورد زد", "fa") is True


def test_module_passes_whitelist_rejects_non_crypto():
    assert passes_whitelist("فوتبال ایران امشب", "fa") is False
