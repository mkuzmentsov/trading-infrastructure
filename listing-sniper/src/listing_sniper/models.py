"""Core data types for the listing-sniper."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

Market = str  # "spot" | "perp" | "unknown"


@dataclass(frozen=True)
class Listing:
    """A parsed Binance listing announcement.

    Title-level parse only — coarse but precise enough to *identify* a new listing. The exact
    open timestamp (needed by the executor) lives in the article body and is fetched on demand
    (see announcements.fetch_detail / parse_open_time).
    """

    article_id: int
    code: str                    # opaque id for the article-detail URL
    title: str
    market: Market               # spot / perp / unknown (inferred from the title)
    tickers: tuple[str, ...]     # extracted token symbols, e.g. ("PARTI",)
    is_launchpool: bool
    listing_date: date | None    # coarse date from the title, if present
    release_ts: datetime | None  # announcement time, if the feed provides it

    @property
    def url(self) -> str:
        return f"https://www.binance.com/en/support/announcement/{self.code}"
