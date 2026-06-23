"""Binance new-listing announcement feed — fetch, parse, and a dedup watcher.

Stdlib-only and network-injectable: the HTTP layer is a swappable callable, so the parsing (the
part with real logic) is fully unit-tested without touching Binance. The CMS endpoint needs no
auth, just a browser User-Agent.

    catalogId 48 = "New Cryptocurrency Listing"  (spot + launchpool + airdrops)
    (the futures-listing catalogId is added once we wire the perp leg; verify it live first)
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import date, datetime, timezone
from typing import Callable

from .models import Listing

_API = "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query"
_DETAIL = "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query"
NEW_LISTING = 48

HttpGet = Callable[[str], dict]

# Uppercase tokens that appear in titles/parens but are NOT tickers.
_NOISE = {"USD", "USDT", "USDC", "USDS", "BTC", "ETH", "BNB", "UTC", "ET", "API", "TGE",
          "FDV", "NFT", "AMA", "TBA", "KYC", "P2P", "VIP", "IEO", "ATH"}

_TICKER_PAREN = re.compile(r"\(([A-Z][A-Z0-9]{1,14})\)")            # "... (PARTI) ..."
_TICKER_PERP = re.compile(r"argined\s+([A-Z][A-Z0-9]{1,14})\s+Perpetual")  # "USD<sym>-Margined PARTI Perpetual"
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
# article-body open time, e.g. "... will be opened at 2026-06-20 08:00 (UTC)"
_OPEN_TIME = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2})?\s*\(UTC\)", re.IGNORECASE)


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def fetch_articles(catalog_id: int = NEW_LISTING, page_size: int = 20, page_no: int = 1, *,
                   http: HttpGet = _http_get_json) -> list[dict]:
    """Raw article dicts (id, code, title, releaseDate) for a catalog page, newest first."""
    data = http(f"{_API}?catalogId={catalog_id}&pageNo={page_no}&pageSize={page_size}")
    return ((data or {}).get("data") or {}).get("articles") or []


_QUOTES = ("USDT", "USDC", "FDUSD", "BUSD", "USD")


def _strip_quote(sym: str) -> str:
    """Perp titles sometimes name the full pair ('ARXUSDT Perpetual'); reduce to the base ticker."""
    for q in _QUOTES:
        if len(sym) > len(q) and sym.endswith(q):
            return sym[: -len(q)]
    return sym


def _market(title: str) -> str:
    t = title.lower()
    if "perpetual" in t or "futures" in t:
        return "perp"
    if any(k in t for k in ("will list", "will add", "launchpool", "hodler", "introducing", "spot")):
        return "spot"
    return "unknown"


def parse_listing(article: dict) -> Listing:
    """Title-level parse of one announcement into a :class:`Listing`."""
    title = article.get("title") or ""
    tickers: list[str] = []
    for raw in (*_TICKER_PAREN.findall(title), *_TICKER_PERP.findall(title)):
        sym = _strip_quote(raw)
        if sym not in _NOISE and sym not in tickers:
            tickers.append(sym)
    dm = _DATE.search(title)
    rel = article.get("releaseDate") or article.get("publishDate")
    return Listing(
        article_id=int(article["id"]),
        code=article.get("code") or "",
        title=title,
        market=_market(title),
        tickers=tuple(tickers),
        is_launchpool="launchpool" in title.lower(),
        listing_date=date.fromisoformat(dm.group(1)) if dm else None,
        release_ts=datetime.fromtimestamp(rel / 1000, tz=timezone.utc) if rel else None,
    )


def fetch_detail_body(code: str, *, http: HttpGet = _http_get_json) -> str:
    """The article body text (where the exact open time lives)."""
    data = http(f"{_DETAIL}?code={code}")
    return ((data or {}).get("data") or {}).get("body") or ""


def parse_open_time(body: str) -> datetime | None:
    """Extract the precise listing/open time (UTC) from an article body, if stated."""
    m = _OPEN_TIME.search(body or "")
    if not m:
        return None
    return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


class AnnouncementWatcher:
    """Polls the feed and returns only listings not seen before. Pre-load ``seen`` from persisted
    state so a restart doesn't re-emit (and re-trade) old announcements. State persistence is the
    caller's job — the watcher just exposes :attr:`seen`."""

    def __init__(self, *, catalog_id: int = NEW_LISTING, page_size: int = 20,
                 http: HttpGet = _http_get_json, seen: set[int] | None = None) -> None:
        self.catalog_id = catalog_id
        self.page_size = page_size
        self._http = http
        self._seen: set[int] = set(seen or ())

    @property
    def seen(self) -> frozenset[int]:
        return frozenset(self._seen)

    def poll(self) -> list[Listing]:
        """Fetch the feed; return newly-seen listings (and mark them seen)."""
        fresh: list[Listing] = []
        for art in fetch_articles(self.catalog_id, self.page_size, http=self._http):
            aid = int(art["id"])
            if aid in self._seen:
                continue
            self._seen.add(aid)
            fresh.append(parse_listing(art))
        return fresh
