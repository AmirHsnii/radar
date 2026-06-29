"""Tests for coin CSV import and embed text."""
from app.modules.admin.csv_import import parse_coin_csv
from app.modules.coins.embed_text import coin_embed_text, parse_aliases_value


def test_parse_coin_csv_with_aliases():
    raw = (
        "symbol,name,aliases\n"
        "BTC,Bitcoin,بیت‌کوین,Bitcoin,digital gold\n"
        "ETH,Ethereum,اتریوم\n"
    ).encode("utf-8")
    rows = parse_coin_csv(raw)
    assert len(rows) == 2
    assert rows[0].symbol == "BTC"
    assert "بیت" in " ".join(rows[0].aliases)
    assert "digital gold" in rows[0].aliases or "Bitcoin" in rows[0].aliases


def test_coin_embed_text_includes_aliases():
    text = coin_embed_text("BTC", "Bitcoin", ["بیت‌کوین", "digital gold"])
    assert "BTC" in text
    assert "Bitcoin" in text
    assert "بیت" in text
    assert "cryptocurrency" in text


def test_parse_coin_csv_semicolon_delimiter():
    raw = "symbol;name;aliases\nBTC;Bitcoin;بیت کوین\n".encode("utf-8")
    rows = parse_coin_csv(raw)
    assert len(rows) == 1
    assert rows[0].symbol == "BTC"
    assert rows[0].name == "Bitcoin"
