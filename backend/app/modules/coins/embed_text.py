"""Build embedding text for coins — includes symbol, name, and aliases."""
from __future__ import annotations

import json
import re

_ALIAS_SPLIT = re.compile(r"[,;|]")


def parse_aliases_value(raw: str | list[str] | None) -> list[str]:
    """Normalize aliases from JSON string, CSV cell, or list."""
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                data = json.loads(text)
                items = data if isinstance(data, list) else [text]
            except json.JSONDecodeError:
                items = _ALIAS_SPLIT.split(text)
        else:
            items = _ALIAS_SPLIT.split(text)

    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        alias = str(item).strip()
        if alias and alias.lower() not in seen:
            seen.add(alias.lower())
            result.append(alias)
    return result


def aliases_to_json(aliases: list[str]) -> str | None:
    cleaned = parse_aliases_value(aliases)
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


def _auto_aliases(symbol: str, name: str) -> list[str]:
    """Common spelling variants for well-known tickers."""
    sym = symbol.strip().upper()
    nm = name.strip()
    extras: list[str] = []
    if sym == "BTC":
        extras.extend(["Bitcoin", "بیت کوین", "بیت‌کوین", "بیتکوین"])
    elif sym == "ETH":
        extras.extend(["Ethereum", "اتریوم", "Ether"])
    elif sym == "SOL":
        extras.extend(["Solana", "سولانا"])
    elif sym == "XRP":
        extras.extend(["Ripple", "ریپل"])
    if nm and nm.lower() != sym.lower():
        extras.append(nm)
    return extras


def coin_embed_text(symbol: str, name: str, aliases: str | list[str] | None = None) -> str:
    """
    Text embedded for semantic coin matching.

    Includes symbol, full name, and aliases (Persian/English nicknames)
    so news mentioning «بیت‌کوین» can match BTC even without exact symbol.
    """
    symbol = symbol.strip().upper()
    name = name.strip()
    alias_list = parse_aliases_value(aliases)
    alias_list.extend(a for a in _auto_aliases(symbol, name) if a not in alias_list)

    parts = [
        symbol, name, *alias_list,
        f"{name} {symbol} crypto",
        "cryptocurrency", "blockchain", "digital asset",
    ]
    # Deduplicate while preserving order (case-insensitive)
    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return " ".join(unique)
