"""Walk-forward harness + block-bootstrap Sharpe CI (§4.5, §5b)."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from algo_trading_bot.validation.stats import block_bootstrap_sharpe
from algo_trading_bot.validation.walk_forward import WalkForward, WalkForwardConfig


def test_walk_forward_blocks_cover_index_rolling():
    idx = pd.date_range("2020-01-01", periods=365 * 4, freq="D", tz="UTC")
    wf = WalkForward(WalkForwardConfig(train_window=timedelta(days=365),
                                       test_window=timedelta(days=180), retrain_every=timedelta(days=180)))
    blocks = wf.blocks(idx)
    assert len(blocks) >= 4
    for tr_s, tr_e, te_s, te_e in blocks:
        assert tr_s <= tr_e == te_s < te_e          # contiguous train->test, no gap
        assert (te_s - tr_s) <= timedelta(days=366)  # rolling: train window bounded


def test_walk_forward_run_no_refit_scores_each_block():
    idx = pd.date_range("2020-01-01", periods=365 * 4, freq="D", tz="UTC")
    ser = pd.Series(np.ones(len(idx)) * 0.001, index=idx)
    wf = WalkForward(WalkForwardConfig(train_window=timedelta(days=365),
                                       test_window=timedelta(days=180), retrain_every=timedelta(days=180)))
    blocks = wf.run(ser, fit_fn=lambda s, e: None,
                    eval_fn=lambda _, ts, te: ser[(ser.index >= ts) & (ser.index < te)])
    assert blocks and all(len(b.result) > 0 for b in blocks)


def test_block_bootstrap_sharpe_separates_signal_from_noise():
    rng = np.random.default_rng(0)
    n, ppy = 1500, 252
    signal = 0.0008 + rng.normal(0, 0.01, n)          # positive drift
    noise = rng.normal(0, 0.01, n)                     # zero drift
    bs_s = block_bootstrap_sharpe(signal, ppy, block=21, n_boot=1000, seed=1)
    bs_n = block_bootstrap_sharpe(noise, ppy, block=21, n_boot=1000, seed=1)
    assert bs_s["ci_low"] <= bs_s["sharpe"] <= bs_s["ci_high"]   # point inside CI
    assert bs_s["p_positive"] > 0.9 and bs_s["ci_low"] > 0       # signal robustly positive
    assert bs_n["p_positive"] < bs_s["p_positive"]               # noise less confident than signal
    assert bs_n["ci_low"] < bs_s["ci_low"]                       # and a lower-bounded, wider CI
