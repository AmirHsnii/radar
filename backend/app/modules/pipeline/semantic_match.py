"""Keyword and fuzzy helpers that complement embedding-based classification."""
from __future__ import annotations

import re

from app.modules.coins.embed_text import parse_aliases_value


def _contains_term(text: str, term: str) -> bool:
    term = term.strip()
    if not term or len(term) < 2:
        return False
    if len(term) <= 5 and term.isalpha():
        pat = rf"(?<![\w/]){re.escape(term)}(?![\w/])"
        return bool(re.search(pat, text, re.IGNORECASE))
    return term.lower() in text.lower()


def match_coins_by_keywords(
    text: str,
    coins: list[tuple[str, str, str | list[str] | None]],
    *,
    max_results: int = 5,
) -> list[str]:
    """
    Match coins by symbol, English name, and aliases in free text.

    coins: list of (symbol, name, aliases_raw)
    """
    if not text.strip():
        return []

    matched: list[str] = []
    for symbol, name, aliases_raw in coins:
        terms = [symbol, name, *parse_aliases_value(aliases_raw)]
        if any(_contains_term(text, term) for term in terms):
            matched.append(symbol.upper())

    # Preserve feed order (usually specificity by coin list order), dedupe
    seen: set[str] = set()
    ordered: list[str] = []
    for sym in matched:
        if sym not in seen:
            seen.add(sym)
            ordered.append(sym)
    return ordered[:max_results]


def resolve_default_category(
    categories: list[tuple[int, str, str]],
    default_name: str,
) -> tuple[int, str, str] | None:
    """
    Find fallback category by exact or partial name match.

    categories: (id, name, name_fa)
    default_name: setting value e.g. «اخبار بازار» or «market-news»
    """
    needle = default_name.strip().lower()
    if not needle or not categories:
        return None

    exact = [
        c for c in categories
        if c[1].lower() == needle or c[2].lower() == needle
    ]
    if exact:
        return exact[0]

    partial = [
        c for c in categories
        if needle in c[1].lower() or needle in c[2].lower()
        or c[1].lower() in needle or c[2].lower() in needle
    ]
    if partial:
        return partial[0]

    if needle in {"بازار", "market"}:
        for c in categories:
            if c[1] == "market-news" or "بازار" in c[2]:
                return c

    return None
