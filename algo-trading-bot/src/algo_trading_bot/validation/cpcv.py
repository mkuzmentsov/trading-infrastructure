"""Combinatorial Purged Cross-Validation + Probability of Backtest Overfitting (§4.2).

Two tools, both from López de Prado (AFML ch. 11–12):

* :class:`CombinatorialPurgedCV` — instead of one train/test split, choose k of N
  purged groups as the test set in *all* combinations, yielding a distribution of OOS
  backtest paths rather than a single number.

* :func:`cscv_pbo` — the Probability of Backtest Overfitting via Combinatorially
  Symmetric Cross-Validation. Given a matrix of per-period performance across the N
  *trials* a search considered (e.g. every grid config), it estimates how often the
  in-sample-best trial lands below the OOS median — i.e. how much the selection itself
  overfit. PBO is the number that turns "my best config had Sharpe X" into "...and here
  is the probability that X was luck."
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb
from typing import Iterator

import numpy as np
import pandas as pd


class CombinatorialPurgedCV:
    def __init__(self, n_groups: int = 6, n_test_groups: int = 2, embargo_pct: float = 0.01) -> None:
        self.n_groups = n_groups
        self.n_test_groups = n_test_groups
        self.embargo_pct = embargo_pct

    def split(
        self, X: pd.DataFrame, label_spans: pd.Series
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield (train_idx, test_idx) for every C(n_groups, n_test_groups) combination,
        with train samples whose label span overlaps any test group purged + embargoed."""
        n = len(X)
        if n == 0:
            return
        idx = X.index
        spans = label_spans.reindex(idx)
        bounds = np.linspace(0, n, self.n_groups + 1).astype(int)
        groups = [np.arange(bounds[g], bounds[g + 1]) for g in range(self.n_groups)]
        embargo = int(n * self.embargo_pct)

        for combo in combinations(range(self.n_groups), self.n_test_groups):
            test_pos = np.concatenate([groups[g] for g in combo])
            test_pos.sort()
            # test windows are the (possibly disjoint) chosen groups
            windows = [(groups[g][0], groups[g][-1]) for g in combo]
            keep = []
            test_set = set(test_pos.tolist())
            for i in range(n):
                if i in test_set:
                    continue
                t = idx[i]
                span_end = spans.iloc[i]
                drop = False
                for lo, hi in windows:
                    w_start, w_end = idx[lo], idx[hi]
                    overlaps = (not pd.isna(span_end)) and (t <= w_end) and (span_end >= w_start)
                    in_embargo = w_end < t <= idx[min(hi + embargo, n - 1)]
                    if overlaps or in_embargo:
                        drop = True
                        break
                if not drop:
                    keep.append(i)
            yield np.array(keep, dtype=int), test_pos

    def n_paths(self) -> int:
        """Number of distinct OOS backtest paths this configuration recombines into."""
        return comb(self.n_groups, self.n_test_groups) * self.n_test_groups // self.n_groups


@dataclass
class PBOResult:
    pbo: float                     # P(in-sample-best trial below OOS median) — overfit prob.
    n_trials: int
    n_blocks: int
    n_combos: int
    prob_oos_loss: float           # P(selected trial has OOS Sharpe < 0)
    median_oos_sharpe: float       # median OOS Sharpe of the IS-selected trial
    perf_degradation: float        # OLS slope of OOS vs IS Sharpe across combos (<1 = decay)

    def summary(self) -> str:
        return (
            f"PBO={self.pbo:.2f}  P(OOS loss)={self.prob_oos_loss:.2f}  "
            f"median OOS Sharpe(selected)={self.median_oos_sharpe:.2f}  "
            f"IS→OOS slope={self.perf_degradation:+.2f}  "
            f"({self.n_trials} trials, {self.n_combos} CSCV splits)"
        )


def _col_sharpe(block: np.ndarray) -> np.ndarray:
    """Per-column (per-trial) Sharpe over the rows of ``block`` (T x N)."""
    if block.shape[0] < 2:
        return np.zeros(block.shape[1])
    mu = block.mean(axis=0)
    sd = block.std(axis=0, ddof=1)
    out = np.zeros_like(mu)
    nz = sd > 0
    out[nz] = mu[nz] / sd[nz]
    return out


def cscv_pbo(returns_matrix: pd.DataFrame, n_blocks: int = 10) -> PBOResult:
    """Probability of Backtest Overfitting via CSCV (AFML ch. 11).

    ``returns_matrix`` is (T periods x N trials) of per-period returns — one column per
    configuration the search evaluated. Rows are split into ``n_blocks`` contiguous
    blocks; for every way to choose half the blocks as in-sample, the IS-best trial is
    found and its *out-of-sample rank* recorded. PBO is the fraction of splits where it
    fell below the OOS median (logit < 0).
    """
    M = returns_matrix.dropna(how="any").to_numpy()
    T, N = M.shape
    if N < 2 or T < n_blocks * 2:
        return PBOResult(float("nan"), N, n_blocks, 0, float("nan"), float("nan"), float("nan"))
    if n_blocks % 2 == 1:
        n_blocks -= 1

    block_idx = np.array_split(np.arange(T), n_blocks)
    logits, oos_sel, is_sel, oos_sel_sharpe = [], [], [], []

    for is_blocks in combinations(range(n_blocks), n_blocks // 2):
        is_rows = np.concatenate([block_idx[b] for b in is_blocks])
        oos_rows = np.concatenate([block_idx[b] for b in range(n_blocks) if b not in is_blocks])
        is_perf = _col_sharpe(M[is_rows])
        oos_perf = _col_sharpe(M[oos_rows])

        n_star = int(np.argmax(is_perf))
        # OOS rank of the selected trial (1 = worst ... N = best)
        order = oos_perf.argsort()
        ranks = np.empty(N)
        ranks[order] = np.arange(1, N + 1)
        w = ranks[n_star] / (N + 1)
        logits.append(np.log(w / (1 - w)))
        is_sel.append(is_perf[n_star])
        oos_sel.append(oos_perf[n_star])
        oos_sel_sharpe.append(oos_perf[n_star])

    logits = np.array(logits)
    oos_sel = np.array(oos_sel)
    pbo = float(np.mean(logits < 0))
    prob_loss = float(np.mean(oos_sel < 0))
    # IS->OOS performance decay across splits (slope of OOS on IS for the selected trial)
    is_arr = np.array(is_sel)
    slope = float(np.polyfit(is_arr, oos_sel, 1)[0]) if np.ptp(is_arr) > 0 else float("nan")

    return PBOResult(
        pbo=pbo,
        n_trials=N,
        n_blocks=n_blocks,
        n_combos=len(logits),
        prob_oos_loss=prob_loss,
        median_oos_sharpe=float(np.median(oos_sel)),
        perf_degradation=slope,
    )


# Backwards-compatible helper kept for callers that already hold IS/OOS perf arrays.
def probability_of_backtest_overfitting(returns_matrix: pd.DataFrame, n_blocks: int = 10) -> float:
    return cscv_pbo(returns_matrix, n_blocks).pbo
