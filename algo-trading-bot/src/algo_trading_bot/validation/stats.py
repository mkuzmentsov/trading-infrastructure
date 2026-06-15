"""Small statistical helpers used by the validation harness."""

from __future__ import annotations

import math


def norm_cdf(x: float) -> float:
    """Standard-normal CDF via the error function (exact, no SciPy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
