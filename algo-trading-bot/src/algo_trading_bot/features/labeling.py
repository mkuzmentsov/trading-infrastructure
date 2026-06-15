"""Triple-barrier labeling + sample weighting (§2.2).

Label each event by which barrier it touches first: take-profit (+1), stop-loss
(-1), or the vertical time limit (0). This aligns training with how the bot
actually exits (§2.5 stops are mapped from these barriers). Overlapping labels are
down-weighted by concurrency so the model isn't fooled by redundant samples
(López de Prado, AFML ch. 3–4).
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from ..core.types import Label, Symbol


def triple_barrier_labels(
    prices: pd.Series,
    events: pd.DatetimeIndex,
    pt_sl: tuple[float, float],
    vertical: timedelta,
    symbol: Symbol,
    target_vol: pd.Series | None = None,
) -> list[Label]:
    """Compute triple-barrier outcomes for each event timestamp.

    ``pt_sl`` = (take-profit, stop-loss) widths as multiples of ``target_vol``
    (dynamic barriers scale with volatility). ``vertical`` is the max holding time.
    """
    raise NotImplementedError(
        "for each event: set horizontal barriers at +pt/-sl*vol, vertical at event+vertical; "
        "outcome = sign of the first barrier touched; ret = return to touch."
    )


def concurrency_weights(labels: list[Label], prices: pd.Series) -> list[float]:
    """Sample weights inversely proportional to label overlap (uniqueness), §2.2."""
    raise NotImplementedError("count concurrent labels per bar; weight = avg(1/concurrency)")
