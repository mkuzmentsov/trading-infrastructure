"""Per-run report assembly (§3.3, §3.4).

Bundles equity curve + returns + trade ledger + MetricsReport + RunProvenance into
a single serializable artifact. Every run writes one; a run without provenance is
not trusted (§3.4).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..engine.backtest import RunProvenance
from .metrics import MetricsReport


@dataclass
class RunReport:
    provenance: RunProvenance
    equity_curve: pd.Series
    returns: pd.Series
    ledger: pd.DataFrame  # trade-by-trade (§3.3)
    metrics: MetricsReport

    def save(self, path: str) -> None:
        """Persist report + provenance (Parquet for series, JSON for metrics/provenance)."""
        raise NotImplementedError("write equity/returns/ledger to parquet; metrics+provenance to json")
