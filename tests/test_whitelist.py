from app.modules.crawler.whitelist import passes_whitelist


def test_passes_fa_bitcoin():
    assert passes_whitelist("بیت‌کوین به رکورد جدید رسید", "fa")


def test_blocks_unrelated_fa():
    assert not passes_whitelist("پیش‌بینی آب و هوای فردا", "fa")


def test_en_empty_whitelist_allows_all():
    assert passes_whitelist("Local weather forecast for tomorrow", "en")


def test_en_whitelist_when_configured():
    from app.modules.crawler.whitelist import whitelist_filter
    whitelist_filter._keywords_en = ["bitcoin", "crypto"]
    assert passes_whitelist("Bitcoin hits new ATH", "en")
    assert not passes_whitelist("Local weather forecast", "en")
