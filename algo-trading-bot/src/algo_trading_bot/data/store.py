"""Point-in-time storage (§2.1, §3.4).

Parquet on disk (one file per venue/symbol), read + filtered with pandas. The
non-negotiable invariant: every record carries ``knowable_at`` and reads are
filterable by it, so a backtest at simulated time T can only see rows with
``knowable_at <= T``. No lookahead is then a property of the store, not of the
discipline of every caller.

Snapshots are content-addressed (a hash over the queried slice) so a run can be
pinned to an exact dataset for reproducibility (§3.4, NFR2). DuckDB/ClickHouse are
a later scaling step; pandas is enough at this size.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pandas as pd

from ..core.types import Bar, FundingPoint, Symbol, VenueId

_COLUMNS = ["symbol", "venue", "ts", "open", "high", "low", "close", "volume", "knowable_at"]


class PointInTimeStore:
    """Append-only, point-in-time bar store backed by per-(venue,symbol) Parquet files."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        (self.root / "bars").mkdir(parents=True, exist_ok=True)

    # --- paths ---
    def _path(self, venue: str, symbol: str) -> Path:
        return self.root / "bars" / f"{venue}__{symbol}.parquet"

    # --- write ---
    def append_bars(self, bars: list[Bar]) -> None:
        """Merge ``bars`` into their per-(venue,symbol) Parquet files, de-duped on ts."""
        if not bars:
            return
        df = pd.DataFrame(
            {
                "symbol": [b.symbol for b in bars],
                "venue": [b.venue for b in bars],
                "ts": [b.ts for b in bars],
                "open": [b.open for b in bars],
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
                "volume": [b.volume for b in bars],
                "knowable_at": [b.known_at() for b in bars],
            }
        )
        for (venue, symbol), grp in df.groupby(["venue", "symbol"], sort=False):
            path = self._path(str(venue), str(symbol))
            if path.exists():
                grp = pd.concat([pd.read_parquet(path), grp], ignore_index=True)
            grp = (
                grp.drop_duplicates(subset=["ts"], keep="last")
                .sort_values("ts")
                .reset_index(drop=True)
            )
            grp.to_parquet(path, index=False)

    def append_funding(self, points: list[FundingPoint]) -> None:
        raise NotImplementedError("funding ingestion lands with the context-feature slice")

    # --- read ---
    def _frame(
        self, symbols: list[Symbol], venue: str | None, start: datetime, end: datetime
    ) -> pd.DataFrame:
        frames = []
        for sym in symbols:
            for path in (self.root / "bars").glob(f"*__{sym}.parquet"):
                if venue and not path.name.startswith(f"{venue}__"):
                    continue
                frames.append(pd.read_parquet(path))
        if not frames:
            return pd.DataFrame(columns=_COLUMNS)
        df = pd.concat(frames, ignore_index=True)
        start = pd.Timestamp(start).tz_convert("UTC") if pd.Timestamp(start).tzinfo else pd.Timestamp(start, tz="UTC")
        end = pd.Timestamp(end).tz_convert("UTC") if pd.Timestamp(end).tzinfo else pd.Timestamp(end, tz="UTC")
        return df[(df["ts"] >= start) & (df["ts"] <= end)].reset_index(drop=True)

    def read_ordered(
        self,
        symbols: list[Symbol],
        start: datetime,
        end: datetime,
        as_of: datetime | None = None,
        venue: str | None = None,
    ) -> Iterator[Bar]:
        """Yield bars in ``knowable_at`` order, optionally only those knowable by
        ``as_of`` (point-in-time read). This is what the historical source consumes."""
        df = self._frame(symbols, venue, start, end)
        if df.empty:
            return
        if as_of is not None:
            cutoff = pd.Timestamp(as_of, tz="UTC") if pd.Timestamp(as_of).tzinfo is None else pd.Timestamp(as_of)
            df = df[df["knowable_at"] <= cutoff]
        df = df.sort_values(["knowable_at", "symbol"]).reset_index(drop=True)
        for r in df.itertuples(index=False):
            yield Bar(
                symbol=Symbol(r.symbol),
                ts=r.ts.to_pydatetime(),
                open=r.open,
                high=r.high,
                low=r.low,
                close=r.close,
                volume=r.volume,
                venue=VenueId(r.venue),
                knowable_at=r.knowable_at.to_pydatetime(),
            )

    # --- reproducibility (§3.4) ---
    def snapshot_id(
        self, symbols: list[Symbol], start: datetime, end: datetime, venue: str | None = None
    ) -> str:
        """Stable content hash of the queried slice, recorded in every run's provenance."""
        df = self._frame(symbols, venue, start, end).sort_values(["symbol", "ts"])
        h = hashlib.sha256()
        h.update(",".join(sorted(symbols)).encode())
        h.update(str(len(df)).encode())
        if not df.empty:
            h.update(str(df["ts"].iloc[0]).encode())
            h.update(str(df["ts"].iloc[-1]).encode())
            h.update(pd.util.hash_pandas_object(df[["ts", "close"]], index=False).values.tobytes())
        return h.hexdigest()[:16]
