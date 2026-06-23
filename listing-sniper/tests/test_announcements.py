"""Announcement parsing + dedup watcher — fully offline (network injected)."""

from datetime import date, datetime, timezone

from listing_sniper.announcements import (
    AnnouncementWatcher,
    fetch_articles,
    parse_listing,
    parse_open_time,
)


def _art(aid, title, code="c", release_ms=None):
    return {"id": aid, "code": code, "title": title, "releaseDate": release_ms}


def test_parse_spot_listing_with_ticker_and_date():
    lst = parse_listing(_art(1, "Binance Will List Particle Network (PARTI) with Seed Tag Applied (2026-06-20)"))
    assert lst.market == "spot"
    assert lst.tickers == ("PARTI",)
    assert lst.listing_date == date(2026, 6, 20)
    assert not lst.is_launchpool


def test_parse_perp_listing_ticker_outside_parens():
    lst = parse_listing(_art(2, "Binance Futures Will Launch USDⓈ-Margined PARTI Perpetual Contract With Up to 75x Leverage"))
    assert lst.market == "perp"
    assert lst.tickers == ("PARTI",)


def test_perp_full_pair_reduced_to_base_ticker():
    # Binance sometimes names the full pair in perp titles ("ARXUSDT Perpetual")
    lst = parse_listing(_art(20, "Binance Futures Will Launch USDⓈ-Margined ARXUSDT Perpetual Contract"))
    assert lst.market == "perp" and lst.tickers == ("ARX",)


def test_parse_multiple_tickers():
    lst = parse_listing(_art(3, "Binance Will Add Foo (FOO) and Bar (BAR) to Margin"))
    assert lst.tickers == ("FOO", "BAR")


def test_noise_tokens_filtered():
    # parenthesised non-tickers (quote ccys, dates) must not be picked up
    lst = parse_listing(_art(4, "Binance Adds New JPY Spot Trading Pairs (USDT) (2026-06-26)"))
    assert lst.tickers == ()
    assert lst.listing_date == date(2026, 6, 26)


def test_launchpool_flag():
    lst = parse_listing(_art(5, "Introducing Hyperlane (HYPER) on Binance Launchpool!"))
    assert lst.is_launchpool and lst.market == "spot" and lst.tickers == ("HYPER",)


def test_multi_tradfi_perp_has_no_single_ticker():
    lst = parse_listing(_art(6, "Binance Futures Will Launch Multiple USDⓈ-Margined TradFi Perpetual Contracts (2026-06-29)"))
    assert lst.market == "perp" and lst.tickers == ()


def test_release_ts_parsed():
    lst = parse_listing(_art(7, "Binance Will List X (X)", release_ms=1_782_000_000_000))
    assert lst.release_ts == datetime.fromtimestamp(1_782_000_000, tz=timezone.utc)


def test_url_property():
    assert parse_listing(_art(8, "t", code="abc123")).url.endswith("/announcement/abc123")


def test_parse_open_time_from_body():
    body = "Trading for the PARTI/USDT pair will be opened at 2026-06-20 08:00 (UTC)."
    assert parse_open_time(body) == datetime(2026, 6, 20, 8, 0, tzinfo=timezone.utc)
    assert parse_open_time("no time here") is None


def test_fetch_articles_uses_injected_http():
    calls = {}

    def fake_http(url):
        calls["url"] = url
        return {"data": {"articles": [_art(1, "a"), _art(2, "b")]}}

    arts = fetch_articles(catalog_id=48, page_size=5, http=fake_http)
    assert len(arts) == 2
    assert "catalogId=48" in calls["url"] and "pageSize=5" in calls["url"]


def test_watcher_dedups_across_polls():
    feed = [_art(10, "Binance Will List Aaa (AAA)"), _art(11, "Binance Will List Bbb (BBB)")]

    def fake_http(_url):
        return {"data": {"articles": list(feed)}}

    w = AnnouncementWatcher(http=fake_http)
    first = w.poll()
    assert {l.tickers[0] for l in first} == {"AAA", "BBB"}  # both new
    assert w.poll() == []                                   # nothing new on re-poll
    feed.insert(0, _art(12, "Binance Will List Ccc (CCC)"))  # a newer one appears
    fresh = w.poll()
    assert [l.tickers[0] for l in fresh] == ["CCC"]


def test_watcher_preloaded_seen_suppresses():
    def fake_http(_url):
        return {"data": {"articles": [_art(20, "Binance Will List Z (Z)")]}}

    w = AnnouncementWatcher(http=fake_http, seen={20})
    assert w.poll() == []                                   # already seen -> not re-emitted
