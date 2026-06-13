"""Chart-pattern detection (pure, stdlib-only).

Single source of truth for "is there a double top / double bottom here?". Used
verbatim by both the live bot (main.py) and the backtester (backtest.py), so the
two can never drift apart.

The detector is strictly CAUSAL: given a window of candles up to and including
the current bar, it reports whether the CURRENT bar just *confirmed* a pattern
(price closed beyond the neckline for the first time). It never looks at future
bars — a swing pivot is only "confirmed" once `pivot_lookback` trailing bars
exist after it, all of which are in the past relative to the confirmation bar.
So backtest PnL is honest.

Candle format: a list of dicts (or any mapping) with float-coercible keys
    time, open, high, low, close
ordered oldest→newest. `time` is the candle OPEN time in ms (used as a stable
dedup key across loops, since window offsets shift but timestamps don't).

Double top  → bearish → trade SHORT. Two ≈equal swing highs, an intervening
              trough (the neckline); confirmed when a bar closes BELOW the neckline.
Double bottom → bullish → trade LONG. Two ≈equal swing lows, an intervening peak
              (the neckline); confirmed when a bar closes ABOVE the neckline.

Measured-move geometry (consumed by strategy.py):
    height      = |extreme_level − neckline|   (pattern height)
    target      = neckline ∓ height            (project the height past the break)
    extreme_level = the further-out of the two peaks/troughs (stop sits beyond it)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Mapping


@dataclass(frozen=True)
class PatternCfg:
    pivot_lookback: int = 5          # bars each side required to qualify a swing pivot
    peak_tolerance_pct: float = 0.03  # two peaks/troughs within this % = "equal"
    min_bars_between: int = 5         # min bars between the two peaks/troughs
    max_bars_between: int = 60        # max bars between them (older = not the same pattern)
    max_break_bars: int = 0           # 0 = off. Else the neckline break must occur within this many
                                      # bars of the 2nd peak/trough — rejects STALE breaks that fire
                                      # long after the pattern (price wandered, even retested the highs).
    min_trough_depth_pct: float = 0.03  # neckline must retrace >= this fraction from the peaks
    max_trough_depth_pct: float = 0.0   # 0 = no cap. Else reject if the trough between the peaks
                                        # is DEEPER than this — a real double top has a shallow
                                        # pullback, not a full crash-and-recover (a deep V).
    entry_mode: str = "neckline_break"  # "neckline_break": confirm on a close beyond the neckline.
                                        # "second_peak": enter as soon as the 2nd peak/trough is
                                        # confirmed (~pivot_lookback bars after it) — don't wait for
                                        # the neckline. Better price; more false signals.
    # --- optional quality filters (0 = disabled) ---
    trend_ma: int = 0                # require regime alignment: only SHORT double-tops when
                                     # the close is below the SMA(trend_ma) and only LONG
                                     # double-bottoms when above it (trade WITH the trend).
    vol_confirm_mult: float = 0.0    # require the breakout bar's volume >= this × the average
                                     # volume over the pattern (0 = no volume filter).

    @classmethod
    def from_dict(cls, d: Mapping) -> "PatternCfg":
        d = d or {}
        return cls(
            pivot_lookback=int(d.get("pivot_lookback", 5)),
            peak_tolerance_pct=float(d.get("peak_tolerance_pct", 0.03)),
            min_bars_between=int(d.get("min_bars_between", 5)),
            max_bars_between=int(d.get("max_bars_between", 60)),
            max_break_bars=int(d.get("max_break_bars", 0)),
            min_trough_depth_pct=float(d.get("min_trough_depth_pct", 0.03)),
            max_trough_depth_pct=float(d.get("max_trough_depth_pct", 0.0)),
            entry_mode=str(d.get("entry_mode", "neckline_break")).lower(),
            trend_ma=int(d.get("trend_ma", 0)),
            vol_confirm_mult=float(d.get("vol_confirm_mult", 0.0)),
        )


@dataclass(frozen=True)
class PatternSignal:
    kind: str            # "double_top" | "double_bottom"
    direction: str       # "short" | "long"
    coin: str            # attached by the caller (detect() is coin-agnostic if blank)
    neckline: float      # the break level
    extreme_level: float  # higher of the two peaks (top) / lower of the two troughs (bottom)
    height: float        # |extreme_level - neckline| → drives the measured-move target
    entry_ref: float     # close of the confirmation bar (reference entry price)
    confirm_time: int    # ms timestamp of the confirmation candle (stable dedup key)
    p1_time: int         # ms timestamp of the first peak/trough
    p2_time: int         # ms timestamp of the second peak/trough


def _swing_highs(highs: Sequence[float], k: int) -> list[int]:
    """Indices i that are confirmed swing highs of order k: high[i] is the max of
    [i-k, i+k]. Only indices with k trailing bars (i <= n-1-k) qualify — that
    trailing requirement is what makes detection causal."""
    n = len(highs)
    out: list[int] = []
    for i in range(k, n - k):
        hi = highs[i]
        if hi == max(highs[i - k : i + k + 1]):
            out.append(i)
    return out


def _swing_lows(lows: Sequence[float], k: int) -> list[int]:
    n = len(lows)
    out: list[int] = []
    for i in range(k, n - k):
        lo = lows[i]
        if lo == min(lows[i - k : i + k + 1]):
            out.append(i)
    return out


def _pick_pair(pivots: list[int], cfg: PatternCfg) -> Optional[tuple[int, int]]:
    """Pick the two most recent pivots (p1 earlier, p2 later) separated by
    [min_bars_between, max_bars_between]. Returns None if no valid pair."""
    if len(pivots) < 2:
        return None
    p2 = pivots[-1]
    for p1 in reversed(pivots[:-1]):
        gap = p2 - p1
        if gap < cfg.min_bars_between:
            continue
        if gap > cfg.max_bars_between:
            return None  # pivots only get older from here
        return p1, p2
    return None


def detect(candles: Sequence[Mapping], cfg: PatternCfg, coin: str = "") -> Optional[PatternSignal]:
    """Return a PatternSignal iff the LAST candle in `candles` just confirmed a
    double top or double bottom (a fresh neckline break), else None.

    "Fresh" = the current bar closes beyond the neckline AND the previous bar did
    not, so the signal fires exactly once per pattern.
    """
    n = len(candles)
    k = cfg.pivot_lookback
    # Need at least two pivots (each costs 2k+1 bars) plus the gap + a break bar.
    if n < 2 * k + cfg.min_bars_between + 2:
        return None

    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]
    times = [int(c["time"]) for c in candles]
    vols = [float(c.get("vol", 0.0)) for c in candles]
    cur = n - 1
    prev = n - 2

    def _trend_ok(direction: str) -> bool:
        """Regime alignment: short only below the trend MA, long only above it."""
        if cfg.trend_ma <= 0:
            return True
        if n < cfg.trend_ma:
            return False  # not enough history to judge the trend → stay out
        sma = sum(closes[-cfg.trend_ma:]) / cfg.trend_ma
        return closes[cur] < sma if direction == "short" else closes[cur] > sma

    def _vol_ok(p1: int, p2: int) -> bool:
        """Require the breakout bar to have conviction: its volume >= mult × the
        average volume across the pattern span."""
        if cfg.vol_confirm_mult <= 0:
            return True
        span = vols[p1:cur + 1]
        avg = sum(span) / len(span) if span else 0.0
        if avg <= 0:
            return True  # no volume data → don't block
        return vols[cur] >= cfg.vol_confirm_mult * avg

    # ---- double top (short): two ≈equal peaks, break BELOW the neckline ----
    top = _pick_pair(_swing_highs(highs, k), cfg)
    if top is not None:
        p1, p2 = top
        h1, h2 = highs[p1], highs[p2]
        neckline = min(lows[p1 : p2 + 1])          # intervening trough
        peak = max(h1, h2)
        depth = (peak - neckline) / neckline if neckline > 0 else 0.0
        equal = abs(h2 - h1) / h1 <= cfg.peak_tolerance_pct if h1 > 0 else False
        deep = depth >= cfg.min_trough_depth_pct and (cfg.max_trough_depth_pct <= 0
                                                       or depth <= cfg.max_trough_depth_pct)
        if cfg.entry_mode == "second_peak":
            fired = cur == p2 + k  # enter as soon as the 2nd peak is confirmed
        else:
            not_stale = cfg.max_break_bars <= 0 or (cur - p2) <= cfg.max_break_bars
            fired = (closes[cur] < neckline <= closes[prev]) and cur > p2 and not_stale
        if (equal and deep and fired and _trend_ok("short") and _vol_ok(p1, p2)):
            return PatternSignal(
                kind="double_top", direction="short", coin=coin,
                neckline=neckline, extreme_level=peak, height=peak - neckline,
                entry_ref=closes[cur], confirm_time=times[cur],
                p1_time=times[p1], p2_time=times[p2],
            )

    # ---- double bottom (long): two ≈equal troughs, break ABOVE the neckline ----
    bot = _pick_pair(_swing_lows(lows, k), cfg)
    if bot is not None:
        p1, p2 = bot
        l1, l2 = lows[p1], lows[p2]
        neckline = max(highs[p1 : p2 + 1])          # intervening peak
        trough = min(l1, l2)
        depth = (neckline - trough) / trough if trough > 0 else 0.0
        equal = abs(l2 - l1) / l1 <= cfg.peak_tolerance_pct if l1 > 0 else False
        deep = depth >= cfg.min_trough_depth_pct and (cfg.max_trough_depth_pct <= 0
                                                      or depth <= cfg.max_trough_depth_pct)
        if cfg.entry_mode == "second_peak":
            fired = cur == p2 + k  # enter as soon as the 2nd trough is confirmed
        else:
            not_stale = cfg.max_break_bars <= 0 or (cur - p2) <= cfg.max_break_bars
            fired = (closes[cur] > neckline >= closes[prev]) and cur > p2 and not_stale
        if (equal and deep and fired and _trend_ok("long") and _vol_ok(p1, p2)):
            return PatternSignal(
                kind="double_bottom", direction="long", coin=coin,
                neckline=neckline, extreme_level=trough, height=neckline - trough,
                entry_ref=closes[cur], confirm_time=times[cur],
                p1_time=times[p1], p2_time=times[p2],
            )

    return None


# --------------------------------------------------------------------------- #
# Self-test: run `python3 patterns.py` to sanity-check the detector on
# synthetic series (a known double top, a known double bottom, and noise).
# --------------------------------------------------------------------------- #
def _mk(prices: list[float], t0: int = 1_000_000) -> list[dict]:
    """Build OHLC candles from a close series (high/low padded ±0.1%)."""
    out = []
    for i, c in enumerate(prices):
        out.append({"time": t0 + i * 3_600_000, "open": c, "high": c * 1.001,
                    "low": c * 0.999, "close": c})
    return out


def _selftest() -> None:
    cfg = PatternCfg(pivot_lookback=3, peak_tolerance_pct=0.03,
                     min_bars_between=4, max_bars_between=60,
                     min_trough_depth_pct=0.03)

    # Double top: peak 110, trough 100 (neckline), peak 110, decline, last bar
    # closes 99 — the first close below the ~99.9 neckline (a fresh break).
    up = [100, 104, 108, 110, 108, 104, 101, 100, 101, 105, 108, 110, 108, 105, 102, 100, 99]
    sig = detect(_mk(up), cfg, coin="TEST")
    assert sig is not None and sig.kind == "double_top", f"expected double_top, got {sig}"
    assert sig.direction == "short"
    assert abs(sig.neckline - 100) < 1.0, sig.neckline
    assert sig.height > 0
    print(f"OK double_top: neckline={sig.neckline:.2f} peak={sig.extreme_level:.2f} "
          f"height={sig.height:.2f} target={sig.neckline - sig.height:.2f}")

    # Double bottom: mirror image — trough 90, peak 100 (neckline), trough 90,
    # rally, last bar closes 101 (first close above the ~100.1 neckline).
    dn = [100, 96, 92, 90, 92, 96, 99, 100, 99, 95, 92, 90, 92, 95, 98, 100, 101]
    sig = detect(_mk(dn), cfg, coin="TEST")
    assert sig is not None and sig.kind == "double_bottom", f"expected double_bottom, got {sig}"
    assert sig.direction == "long"
    assert sig.height > 0
    print(f"OK double_bottom: neckline={sig.neckline:.2f} trough={sig.extreme_level:.2f} "
          f"height={sig.height:.2f} target={sig.neckline + sig.height:.2f}")

    # Monotonic series: no pattern.
    flat = list(range(100, 130))
    assert detect(_mk([float(x) for x in flat]), cfg) is None, "false positive on monotonic series"
    print("OK no false positive on trending series")

    # Confirmation must be FRESH: the bar after the break should not re-fire.
    no_refire = up + [98]  # still below neckline, but not a fresh cross
    assert detect(_mk(no_refire), cfg) is None, "re-fired on a stale break"
    print("OK no re-fire on stale break")

    print("\nall pattern self-tests passed")


if __name__ == "__main__":
    _selftest()
