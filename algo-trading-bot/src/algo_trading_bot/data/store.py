"""Point-in-time storage (§2.1, §3.4).

Parquet on disk + DuckDB for queries to start; ClickHouse/Timescale later. The
non-negotiable invariant: every record carries ``knowable_at`` and reads are
filterable by it, so a backtest at simulated time T can only see rows with
``knowable_at <= T``. No lookahead is then a property of the store, not of the
discipline of every caller.

Snapshots are content-addressed (a hash over the data) so a run can be pinned to
an exact dataset for reproducibility (§3.4, NFR2).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterator

from ..core.types import Bar, FundingPoint, Symbol


class PointInTimeStore:
    """Append-only, point-in-time market data store.

    Backed by partitioned Parquet (by symbol/venue/date) and queried via DuckDB.
    Requires the ``storage`` extra (pyarrow, duckdb).
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # --- write ---
    def append_bars(self, bars: list[Bar]) -> None:
        raise NotImplementedError("write to Parquet partitioned by symbol/venue/date")

    def append_funding(self, points: list[FundingPoint]) -> None:
        raise NotImplementedError

    # --- read ---
    def read_ordered(
        self,
        symbols: list[Symbol],
        start: datetime,
        end: datetime,
        as_of: datetime | None = None,
    ) -> Iterator[Bar | FundingPoint]:
        """Yield records in ``knowable_at`` order, optionally only those knowable by
        ``as_of`` (point-in-time read). This is what the historical source consumes."""
        raise NotImplementedError

    # --- reproducibility (§3.4) ---
    def snapshot_id(self, symbols: list[Symbol], start: datetime, end: datetime) -> str:
        """Stable content hash of the queried slice, recorded in every run's provenance."""
        raise NotImplementedError
