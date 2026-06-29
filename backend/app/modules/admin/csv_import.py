"""CSV parsing helpers for admin bulk import."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass


@dataclass
class CoinRow:
    symbol: str
    name: str
    aliases: list[str]


@dataclass
class CategoryRow:
    name: str
    name_fa: str
    description: str


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1256", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _csv_reader(text: str) -> csv.reader:
    """Detect comma/semicolon/tab delimiters (common Excel regional exports)."""
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return csv.reader(io.StringIO(text), dialect)


def parse_category_csv(raw: bytes) -> list[CategoryRow]:
    """
    Parse categories CSV.

    Expected columns: name, name_fa, description
    Header row is optional (detected when first cell is 'name').
    """
    text = _decode_text(raw)
    reader = _csv_reader(text)
    rows: list[CategoryRow] = []
    for i, row in enumerate(reader):
        if not row or not any(cell.strip() for cell in row):
            continue
        cells = [c.strip() for c in row]
        if i == 0 and cells[0].lower() in ("name", "نام"):
            continue
        if len(cells) < 2:
            continue
        name = cells[0]
        name_fa = cells[1]
        description = cells[2] if len(cells) > 2 else name_fa
        if name and name_fa:
            rows.append(CategoryRow(name=name, name_fa=name_fa, description=description))
    return rows


_SYMBOL_HEADERS = frozenset({"symbol", "نماد", "ticker", "کد"})
_NAME_HEADERS = frozenset({"name", "نام", "coin", "کوین"})
_ALIAS_HEADERS = frozenset({"aliases", "alias", "نام‌های دیگر", "نام های دیگر", "معادل", "nicknames"})


def _is_header_row(cells: list[str]) -> bool:
    first = cells[0].lower()
    return first in _SYMBOL_HEADERS or first in ("symbol", "نماد")


def _column_map(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for i, cell in enumerate(header):
        key = cell.strip().lower()
        if key in _SYMBOL_HEADERS:
            mapping["symbol"] = i
        elif key in _NAME_HEADERS:
            mapping["name"] = i
        elif key in _ALIAS_HEADERS:
            mapping["aliases"] = i
    return mapping


def parse_coin_csv(raw: bytes) -> list[CoinRow]:
    """
    Parse coins CSV.

    Expected columns: symbol, name, aliases (optional)
    aliases cell: comma/semicolon-separated nicknames (Persian or English)
    Header row optional.
    """
    from app.modules.coins.embed_text import parse_aliases_value

    text = _decode_text(raw)
    reader = _csv_reader(text)
    rows: list[CoinRow] = []
    col_map: dict[str, int] | None = None

    for i, row in enumerate(reader):
        if not row or not any(cell.strip() for cell in row):
            continue
        cells = [c.strip() for c in row]

        if i == 0 and _is_header_row(cells):
            col_map = _column_map(cells)
            if "symbol" not in col_map and len(cells) >= 1:
                col_map["symbol"] = 0
            if "name" not in col_map and len(cells) >= 2:
                col_map["name"] = 1
            if "aliases" not in col_map and len(cells) >= 3:
                col_map["aliases"] = 2
            continue

        if col_map:
            symbol = cells[col_map["symbol"]] if "symbol" in col_map and col_map["symbol"] < len(cells) else ""
            name = cells[col_map["name"]] if "name" in col_map and col_map["name"] < len(cells) else ""
            alias_idx = col_map.get("aliases", 2)
            if len(cells) > alias_idx + 1:
                # اکسل بدون quote: aliasهای چندگانه در ستون‌های بعدی
                alias_raw = ",".join(cells[alias_idx:])
            elif len(cells) > alias_idx:
                alias_raw = cells[alias_idx]
            else:
                alias_raw = ""
        else:
            symbol = cells[0] if len(cells) > 0 else ""
            name = cells[1] if len(cells) > 1 else symbol
            alias_raw = ",".join(cells[2:]) if len(cells) > 2 else ""

        symbol = symbol.upper()
        if not symbol:
            continue
        aliases = parse_aliases_value(alias_raw) if alias_raw else []
        rows.append(CoinRow(symbol=symbol, name=name or symbol, aliases=aliases))

    return rows


def parse_whitelist_csv(raw: bytes) -> list[str]:
    """
    Parse whitelist CSV — one keyword per row (first column).
    Header 'keyword' / 'کلمه' is skipped.
    """
    text = _decode_text(raw)
    reader = _csv_reader(text)
    keywords: list[str] = []
    seen: set[str] = set()
    for i, row in enumerate(reader):
        if not row:
            continue
        kw = row[0].strip()
        if not kw:
            continue
        if i == 0 and kw.lower() in ("keyword", "کلمه", "word"):
            continue
        if kw not in seen:
            seen.add(kw)
            keywords.append(kw)
    return keywords
