"""Panel paper book — rebalance accounting, leverage, persistence."""

import json

from algo_trading_bot.engine.panel_paper import PanelPaperBook


def test_rebalance_hits_target_weights_and_charges_fees():
    book = PanelPaperBook.new(starting_cash=10_000.0, fee_bps=10.0)  # 10bps
    prices = {"A": 100.0, "B": 50.0}
    rec = book.rebalance_to({"A": 0.5, "B": -0.5}, prices, "2026-01-01")
    eq = book.equity(prices)
    # weights realized: A long ~50% of equity, B short ~50%
    assert abs(book.positions["A"] * prices["A"] / eq - 0.5) < 0.02
    assert abs(book.positions["B"] * prices["B"] / eq + 0.5) < 0.02
    assert rec["n_trades"] == 2
    assert rec["fees"] > 0 and book.equity(prices) < 10_000.0  # fees paid -> equity below start


def test_equity_marks_to_price_moves():
    book = PanelPaperBook.new(10_000.0, fee_bps=0.0)
    book.rebalance_to({"A": 1.0}, {"A": 100.0}, "2026-01-01")  # all-in long A, no fees
    assert abs(book.equity({"A": 100.0}) - 10_000.0) < 1e-6
    assert abs(book.equity({"A": 110.0}) - 11_000.0) < 1e-6    # +10% price -> +10% equity (1x long)


def test_persistence_roundtrip(tmp_path):
    book = PanelPaperBook.new(10_000.0, fee_bps=4.5)
    book.rebalance_to({"A": 0.3, "B": -0.2}, {"A": 100.0, "B": 50.0}, "2026-01-01")
    p = tmp_path / "book.json"
    book.save(str(p))
    back = PanelPaperBook.load(str(p))
    assert back.cash == book.cash and back.positions == book.positions and back.last_ts == book.last_ts
    assert json.loads(p.read_text())["last_ts"] == "2026-01-01"
