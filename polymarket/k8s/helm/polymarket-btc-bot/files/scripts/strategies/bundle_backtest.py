from __future__ import annotations

import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
_BOT_DIR = Path(__file__).resolve().parents[3]
for _path in (str(_SCRIPTS_DIR), str(_BOT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from backtest import Bar, Trade, group_bars, load_config, load_snapshots, print_report
from btc_next_bar_model import blend_model_probabilities, predict_next_bar_p_up
from ml_signal import predict_p_up as pm_model_predict_p_up
from positions import Position
from strategy import StrategyContext, build_strategy

# Live-side constants not exposed via backtest DEFAULTS. Kept here so the
# replay mirrors main.py gates without importing the live-only `config` module
# (which pulls in env vars and the full config surface).
_FEED_STALE_SECS = 20
_REENTRY_EDGE_PENALTY = 0.05
_MIN_EXIT_BID = 0.03
_AGGRESSIVE_EXIT_SLIPPAGE = 0.02
_ULTRA_CHEAP_TAIL_PRICE = 0.10
# When the live bot rotates away from a market, main.py calls
# `pos_store.park_current_position()` which sets `self.position = None`
# immediately (the parked position moves to `held_positions` and does not
# block new entries). So the global slot is freed the moment the market
# rotates — grace is zero.
_HOLD_RELEASE_GRACE_SECS = 0


def _resolve_events_path(path_arg: str) -> Path:
    path = Path(path_arg)
    if path.is_file():
        return path
    candidate = path / "logs-training-events.jsonl"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"Could not find logs-training-events.jsonl under: {path}")


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _is_external_position_close(event: dict) -> bool:
    if event.get("tracked_position") is False:
        return True
    if event.get("market_start_ts") is None and "redemption" in str(event.get("reason", "")):
        return True
    return False


def _fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _current_bid_for_direction(snap: dict[str, Any], direction: str) -> float:
    pm = snap.get("pm", {})
    if direction == "UP":
        return float(pm.get("up_bid") or 0.0)
    return float(pm.get("down_bid") or 0.0)


def _build_market_timeline(log_dir: str) -> list[dict[str, Any]]:
    """
    Build a timeline of markets ordered by their 5-minute start time.

    Each entry keeps the market_start_ts, market_end_ts, question, and bar_open
    from the earliest snapshot observed for that market.
    """
    snapshots_path = Path(log_dir) / "logs-training.jsonl"
    points: dict[int, dict[str, Any]] = {}
    if not snapshots_path.is_file():
        return []

    for snap in _iter_jsonl(snapshots_path):
        start_ts = int(snap.get("market_start_ts") or 0)
        btc = snap.get("btc", {})
        bar_open = float(btc.get("bar_open") or 0.0)
        if start_ts <= 0 or bar_open <= 0:
            continue
        snap_ts = float(snap.get("ts") or 0.0)
        cur = points.get(start_ts)
        if cur is None or snap_ts < cur["first_ts"]:
            points[start_ts] = {
                "market_start_ts": start_ts,
                "market_end_ts": int(snap.get("market_end_ts") or 0),
                "question": str(snap.get("question", "")),
                "bar_open": bar_open,
                "first_ts": snap_ts,
                "condition_id": str(snap.get("condition_id", "")),
            }

    return sorted(points.values(), key=lambda item: item["market_start_ts"])


def _next_market_close_from_timeline(
    timeline: list[dict[str, Any]],
    market_start_ts: int,
) -> tuple[float | None, dict[str, Any] | None]:
    for idx, point in enumerate(timeline):
        if int(point["market_start_ts"]) != int(market_start_ts):
            continue
        if idx + 1 >= len(timeline):
            return None, None
        nxt = timeline[idx + 1]
        return float(nxt["bar_open"]), nxt
    return None, None


def _build_completed_market_bars(snapshots: list[dict[str, Any]]) -> list[dict[str, float]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for snap in snapshots:
        start_ts = int(snap.get("market_start_ts") or 0)
        if start_ts <= 0:
            continue
        grouped.setdefault(start_ts, []).append(snap)

    bars: list[dict[str, float]] = []
    for start_ts, rows in grouped.items():
        rows.sort(key=lambda item: float(item.get("ts") or 0.0))
        first = rows[0]
        btc0 = first.get("btc", {}) if isinstance(first.get("btc"), dict) else {}
        open_price = float(btc0.get("bar_open") or 0.0)
        if open_price <= 0:
            continue
        highs = []
        lows = []
        closes = []
        for row in rows:
            btc = row.get("btc", {}) if isinstance(row.get("btc"), dict) else {}
            px = float(btc.get("binance_price") or btc.get("current_price") or 0.0)
            if px <= 0:
                continue
            highs.append(px)
            lows.append(px)
            closes.append(px)
        if not closes:
            continue
        bars.append(
            {
                "start_ts": float(start_ts),
                "open": float(open_price),
                "high": float(max(highs)),
                "low": float(min(lows)),
                "close": float(closes[-1]),
            }
        )
    return sorted(bars, key=lambda item: float(item["start_ts"]))


def _settle_hold_to_expiry(
    event: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> tuple[float | None, float, int, str]:
    """
    Settle a tracked open position using the next market's open as the close.

    Returns:
        close_price, pnl, close_ts, note
    """
    market_start_ts = int(event.get("market_start_ts") or 0)
    bar_open = float(event.get("bar_open") or 0.0)
    next_close, next_point = _next_market_close_from_timeline(timeline, market_start_ts)
    if bar_open <= 0 or next_close is None or next_point is None:
        return None, 0.0, 0.0, "incomplete_bundle"

    direction = str(event.get("direction", ""))
    entry = float(event.get("entry_price", 0.0) or 0.0)
    shares = float(event.get("shares", 0.0) or 0.0)
    won = (direction == "UP" and next_close >= bar_open) or (direction == "DOWN" and next_close < bar_open)
    pnl = ((1.0 if won else 0.0) - entry) * shares
    return next_close, pnl, float(next_point["market_start_ts"]), "hold_to_expiry"


@dataclass
class BundleBacktestComparison:
    log_dir: str
    events_file: Path
    ignore_external_positions: bool
    replay_pnl: float
    replay_trades: int
    realized_pnl: float
    realized_trades: int
    final_balance: float
    realized_win_rate: float
    max_drawdown_abs: float
    max_drawdown_ts: float = 0.0
    held_to_expiry_pnl: float = 0.0
    held_to_expiry_trades: int = 0
    incomplete_trades: int = 0
    curve: list[tuple[float, float, float]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "log_dir": self.log_dir,
            "events_file": str(self.events_file),
            "ignore_external_positions": self.ignore_external_positions,
            "replay_pnl": round(self.replay_pnl, 4),
            "replay_trades": self.replay_trades,
            "realized_pnl": round(self.realized_pnl, 4),
            "realized_trades": self.realized_trades,
            "held_to_expiry_pnl": round(self.held_to_expiry_pnl, 4),
            "held_to_expiry_trades": self.held_to_expiry_trades,
            "incomplete_trades": self.incomplete_trades,
            "delta_pnl": round(self.replay_pnl - self.realized_pnl, 4),
            "final_balance": round(self.final_balance, 4),
            "realized_win_rate": round(self.realized_win_rate, 4),
            "max_drawdown_abs": round(self.max_drawdown_abs, 4),
            "max_drawdown_time": _fmt_ts(self.max_drawdown_ts) if self.max_drawdown_ts else "",
        }


@dataclass
class RedemptionCounterfactual:
    log_dir: str
    events_file: Path
    initial_balance: float
    realized_pnl: float
    realized_trades: int
    redemption_pnl: float
    redemption_trades: int
    delta_pnl: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "log_dir": self.log_dir,
            "events_file": str(self.events_file),
            "initial_balance": round(self.initial_balance, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "realized_trades": self.realized_trades,
            "redemption_pnl": round(self.redemption_pnl, 2),
            "redemption_trades": self.redemption_trades,
            "delta_pnl": round(self.delta_pnl, 2),
        }


@dataclass
class BundleBacktestResult:
    yaml_path: str
    log_dir: str
    cfg: dict[str, Any]
    bars: list[Bar]
    trades: list[Trade]

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def total_invested(self) -> float:
        return sum(t.entry_price * t.shares for t in self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.pnl > 0) / len(self.trades)

    @property
    def total_bars(self) -> int:
        return len([b for b in self.bars if b.outcome])

    def print_report(self) -> None:
        print_report(self.cfg, self.trades, self.bars, self.log_dir)

    def print_direct_report(self) -> None:
        print_report(self.cfg, self.trades, self.bars, self.log_dir)

    def compare_to_real(self, ignore_external_positions: bool = True) -> BundleBacktestComparison:
        events_path = _resolve_events_path(self.log_dir)
        opens: list[dict] = []
        closes_by_cid: dict[str, dict] = {}
        for event in _iter_jsonl(events_path):
            event_type = event.get("event")
            if event_type == "position_opened":
                opens.append(event)
                continue
            if event_type != "position_closed":
                continue
            if ignore_external_positions and _is_external_position_close(event):
                continue
            cid = str(event.get("condition_id", ""))
            if cid:
                prev = closes_by_cid.get(cid)
                if prev is None or float(event.get("ts", 0.0)) > float(prev.get("ts", 0.0)):
                    closes_by_cid[cid] = event

        opens.sort(key=lambda item: float(item.get("ts", 0.0)))
        timeline = _build_market_timeline(self.log_dir)

        balance = 100.0
        peak = balance
        max_drawdown_abs = 0.0
        max_drawdown_ts = 0.0
        pnls: list[float] = []
        curve: list[tuple[float, float, float]] = []
        held_pnl = 0.0
        held_trades = 0
        incomplete_trades = 0

        for event in opens:
            cid = str(event.get("condition_id", ""))
            if not cid:
                continue

            close_event = closes_by_cid.get(cid)
            if close_event is not None:
                pnl = float(close_event.get("pnl", 0.0) or 0.0)
                ts = float(close_event.get("ts", 0.0))
            else:
                close_price, pnl, ts, note = _settle_hold_to_expiry(event, timeline)
                if close_price is None:
                    incomplete_trades += 1
                    continue
                held_pnl += pnl
                held_trades += 1

            balance += pnl
            peak = max(peak, balance)
            drawdown = peak - balance
            if drawdown > max_drawdown_abs:
                max_drawdown_abs = drawdown
                max_drawdown_ts = ts
            curve.append((ts, balance, pnl))
            pnls.append(pnl)

        wins = sum(1 for pnl in pnls if pnl > 0)
        realized_win_rate = (wins / len(pnls)) if pnls else 0.0
        realized_pnl = balance - 100.0

        return BundleBacktestComparison(
            log_dir=self.log_dir,
            events_file=events_path,
            ignore_external_positions=ignore_external_positions,
            replay_pnl=self.total_pnl,
            replay_trades=len(self.trades),
            realized_pnl=realized_pnl,
            realized_trades=len(pnls),
            held_to_expiry_pnl=held_pnl,
            held_to_expiry_trades=held_trades,
            incomplete_trades=incomplete_trades,
            final_balance=balance,
            realized_win_rate=realized_win_rate,
            max_drawdown_abs=max_drawdown_abs,
            max_drawdown_ts=max_drawdown_ts,
            curve=curve,
        )

    def compare_hold_to_redemption(self, ignore_external_positions: bool = True) -> RedemptionCounterfactual:
        events_path = _resolve_events_path(self.log_dir)
        closes: list[dict] = []
        opens: list[dict] = []
        for event in _iter_jsonl(events_path):
            if event.get("event") == "position_opened":
                opens.append(event)
            elif event.get("event") == "position_closed":
                if ignore_external_positions and _is_external_position_close(event):
                    continue
                closes.append(event)

        last_snapshot: dict[str, dict] = {}
        snapshots_path = Path(self.log_dir) / "logs-training.jsonl"
        if snapshots_path.is_file():
            for snap in _iter_jsonl(snapshots_path):
                cid = snap.get("condition_id")
                if cid:
                    last_snapshot[str(cid)] = snap

        realized_pnl = sum(float(event.get("pnl", 0.0) or 0.0) for event in closes)
        redemption_pnl = 0.0
        for event in opens:
            cid = str(event.get("condition_id", ""))
            if not cid:
                continue
            snap = last_snapshot.get(cid, {})
            btc = snap.get("btc", {})
            bar_open = float(btc.get("bar_open") or 0.0)
            final = float(btc.get("binance_price") or btc.get("current_price") or 0.0)
            if bar_open <= 0 or final <= 0:
                continue
            direction = str(event.get("direction", ""))
            won = (direction == "UP" and final >= bar_open) or (direction == "DOWN" and final < bar_open)
            entry = float(event.get("entry_price", 0.0) or 0.0)
            shares = float(event.get("shares", 0.0) or 0.0)
            redemption_pnl += ((1.0 if won else 0.0) - entry) * shares

        return RedemptionCounterfactual(
            log_dir=self.log_dir,
            events_file=events_path,
            initial_balance=100.0,
            realized_pnl=realized_pnl,
            realized_trades=len(closes),
            redemption_pnl=redemption_pnl,
            redemption_trades=len(opens),
            delta_pnl=redemption_pnl - realized_pnl,
        )


class BundleBacktestRunner:
    """
    YAML-driven bundle replay engine for PM BTC strategies.

    This wraps the existing backtest logic into a reusable class so callers can
    load any `pm_btc*.yaml` config and replay it against a bundle without
    placing real orders.
    """

    def __init__(self, yaml_path: str | None = None, cfg: dict[str, Any] | None = None):
        if cfg is None and yaml_path is None:
            raise ValueError("Provide either yaml_path or cfg")
        self.yaml_path = yaml_path or ""
        self.cfg = dict(cfg or load_config(self.yaml_path))

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "BundleBacktestRunner":
        return cls(yaml_path=yaml_path)

    def load_bundle(self, log_dir: str) -> tuple[list[dict], list[Bar]]:
        snapshots = load_snapshots(log_dir)
        bars = group_bars(snapshots)
        return snapshots, bars

    def _build_strategy_context(
        self,
        snap: dict,
        cash_amount: float = 0.0,
        prior_snapshots: list[dict[str, Any]] | None = None,
    ) -> StrategyContext:
        btc = snap.get("btc", {})
        pm = snap.get("pm", {})
        feeds = snap.get("feeds", {})
        staleness = feeds.get("staleness", {})
        return StrategyContext(
            cash_amount=float(cash_amount),
            seconds_left=int(snap.get("seconds_left") or 0),
            bar_open=float(btc.get("bar_open") or 0.0),
            current_price=float(btc.get("current_price") or 0.0),
            ret_30s=float(btc.get("ret_30s") or 0.0),
            ret_60s=float(btc.get("ret_60s") or 0.0),
            sigma_5m=float(btc.get("sigma_5m") or 0.0),
            up_bid=float(pm.get("up_bid") or 0.0),
            up_ask=float(pm.get("up_ask") or 0.0),
            up_bid_size=float(pm.get("up_bid_size") or 0.0),
            up_ask_size=float(pm.get("up_ask_size") or 0.0),
            down_bid=float(pm.get("down_bid") or 0.0),
            down_ask=float(pm.get("down_ask") or 0.0),
            down_bid_size=float(pm.get("down_bid_size") or 0.0),
            down_ask_size=float(pm.get("down_ask_size") or 0.0),
            book_events=int(pm.get("book_events") or 0),
            feed_price_age=float(staleness.get("price_age") or 0.0),
            feed_up_age=float(staleness.get("pm_up_age") or 0.0),
            feed_down_age=float(staleness.get("pm_down_age") or 0.0),
            binance_price=float(btc.get("binance_price") or 0.0),
            binance_age=float(btc.get("binance_age") or 0.0),
            ml_p_up=None,
            condition_id=str(snap.get("condition_id") or ""),
            ts=float(snap.get("ts") or 0.0),
            raw_snapshot=snap,
            prior_snapshots=list(prior_snapshots or []),
        )

    def run_direct_strategy(self, log_dir: str) -> BundleBacktestResult:
        return self.run_tick_strategy(log_dir)

    def run_tick_strategy(self, log_dir: str) -> BundleBacktestResult:
        """
        Tick-by-tick replay that mirrors the live bot's decision tree:

        - Entry path evaluates `strategy.evaluate_entry` only on snapshots the
          live bot actually attempted entry on (`context == "try_enter"`).
        - Entry gates (feed staleness, stop-loss reentry guard, per-market SL
          cap, confirmation ticks) match main.py._try_enter.
        - Exit path walks forward through subsequent same-market snapshots and
          dispatches exits via the same ordering as main.py._manage_position:
            * profit_1: trailing → TP → SL(+adverse gate) → strategy → late_cut
            * pm_btc_ml-entry / pm_btc_ml-entry-v2: strategy handles all exits
        - Global one-position slot: live's pos_store tracks ONE position across
          all markets. On market rotation without a prior exit, the position is
          parked to hold-to-expiry (matching main.py lines 754-770) and the
          slot stays occupied for an approximate redemption-lag grace period
          before the next entry can fire.
        """
        snapshots, bars = self.load_bundle(log_dir)
        completed_market_bars = _build_completed_market_bars(snapshots)
        strategy = build_strategy(self.cfg["STRATEGY_NAME"])

        entry_confirmation_ticks = int(self.cfg.get("ENTRY_CONFIRMATION_TICKS", 1))
        min_seconds_left = int(self.cfg.get("ENTRY_MIN_SECONDS_LEFT", 0))
        strategy_name = str(self.cfg.get("STRATEGY_NAME", ""))
        hold_to_expiry_default = bool(strategy.entry_hold_to_expiry())
        stop_loss_market_limit = int(self.cfg.get("STOP_LOSS_MARKET_LIMIT", 1))

        trailing_arm = float(self.cfg.get("TRAILING_ARM_GAIN", 0.20))
        trailing_gap = float(self.cfg.get("TRAILING_STOP_GAP", 0.03))
        take_profit_th = float(self.cfg.get("TAKE_PROFIT", 0.15))
        stop_loss_th = float(self.cfg.get("STOP_LOSS", 0.08))
        sl_arm_delay = float(self.cfg.get("SL_ARM_DELAY_SECS", 60))
        sl_min_adverse = float(self.cfg.get("SL_MIN_ADVERSE_BTC", 0.0015))
        ultra_cheap_sl_delay = float(self.cfg.get("ULTRA_CHEAP_SL_DELAY_SECS", 120))

        bars_by_cid = {bar.condition_id: bar for bar in bars if bar.outcome}

        # Resolution price = next market's bar_open (≈ Polymarket's oracle close
        # at bar end). Live positions settle against the Chainlink 5m price,
        # which tracks the next bar's open more closely than the last observed
        # binance tick of the expiring market (what bars_by_cid uses).
        timeline = _build_market_timeline(log_dir)
        outcome_by_cid: dict[str, str] = {}
        for idx, point in enumerate(timeline):
            cid = str(point.get("condition_id") or "")
            if not cid or idx + 1 >= len(timeline):
                continue
            this_open = float(point.get("bar_open") or 0.0)
            next_open = float(timeline[idx + 1].get("bar_open") or 0.0)
            if this_open <= 0 or next_open <= 0:
                continue
            outcome_by_cid[cid] = "UP" if next_open >= this_open else "DOWN"

        def _expiry_outcome(cid: str) -> str:
            """Outcome for a hold-to-expiry settlement.

            Prefers next-market bar_open (oracle proxy); falls back to the
            intra-market last-tick outcome when the bundle ends before the
            next market is observed.
            """
            outcome = outcome_by_cid.get(cid, "")
            if outcome:
                return outcome
            bar = bars_by_cid.get(cid)
            return bar.outcome if bar else ""

        trades: list[Trade] = []
        position: Position | None = None
        pos_question: str = ""
        pos_debug: dict[str, Any] = {}
        pos_market_end_ts: int = 0
        slot_free_at_ts: float = 0.0

        sl_reentry_guard: dict[tuple[str, str], float] = {}
        market_sl_count: dict[str, int] = {}

        confirm_condition_id = ""
        confirm_action = ""
        confirm_count = 0
        history_by_cid: dict[str, list[dict[str, Any]]] = {}
        prior_prob_cache: dict[int, float | None] = {}

        try_enter_snaps = [s for s in snapshots if s.get("context") == "try_enter"]
        try_enter_snaps.sort(key=lambda s: float(s.get("ts") or 0.0))

        def _combined_ml_p_up(snap: dict[str, Any], seconds_left: int) -> float | None:
            market_start_ts = int(snap.get("market_start_ts") or 0)
            pm_prob = pm_model_predict_p_up(snap)
            if market_start_ts not in prior_prob_cache:
                prior_bars = [bar for bar in completed_market_bars if int(bar["start_ts"]) < market_start_ts]
                prior_prob_cache[market_start_ts] = predict_next_bar_p_up(prior_bars[-64:], market_start_ts=market_start_ts)
            prior_prob = prior_prob_cache.get(market_start_ts)
            combined, _ = blend_model_probabilities(pm_prob, prior_prob, seconds_left)
            return combined

        def _exit_target(current_bid: float, reason: str) -> float:
            if reason in {"stop_loss", "signal_flip"}:
                return max(_MIN_EXIT_BID, current_bid - _AGGRESSIVE_EXIT_SLIPPAGE)
            return max(current_bid, _MIN_EXIT_BID)

        def _record_trade(
            pos: Position,
            snap_ts: float,
            exit_reason: str,
            exit_price: float,
            bar_outcome: str,
            debug: dict,
            question: str,
        ) -> None:
            pnl = round((exit_price - pos.entry_price) * int(pos.shares), 2)
            trades.append(
                Trade(
                    ts=snap_ts,
                    condition_id=pos.condition_id,
                    question=question,
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    shares=int(pos.shares),
                    edge=pos.entry_edge,
                    p_up=pos.entry_p_up,
                    seconds_left=pos.entry_seconds_left,
                    outcome=bar_outcome,
                    exit_reason=exit_reason,
                    exit_price=float(exit_price),
                    pnl=pnl,
                    btc_distance=float(debug.get("btc_distance") or 0.0),
                    book_divergence=float(debug.get("book_divergence") or 0.0),
                    price_source=str(debug.get("price_source") or "?"),
                )
            )

        for snap in try_enter_snaps:
            ts = float(snap.get("ts") or 0.0)
            cid = str(snap.get("condition_id") or "")
            if not cid:
                continue
            prior_rows = list(history_by_cid.get(cid, []))
            hist = history_by_cid.setdefault(cid, [])
            hist.append(snap)
            if len(hist) > 60:
                del hist[:-60]

            pm = snap.get("pm", {})
            btc = snap.get("btc", {})
            feeds = snap.get("feeds", {})

            # ---------- Manage open position ----------
            if position is not None:
                if cid != position.condition_id:
                    # Market rotated without an exit — park to hold-to-expiry
                    # (mirrors main.py line 754-770) and settle at bar outcome.
                    bar_outcome = _expiry_outcome(position.condition_id)
                    if bar_outcome:
                        won = position.direction == bar_outcome
                        exit_price = 1.0 if won else 0.0
                        _record_trade(
                            position, ts,
                            "expiry_win" if won else "expiry_loss",
                            exit_price, bar_outcome, pos_debug, pos_question,
                        )
                    slot_free_at_ts = float(pos_market_end_ts or ts) + _HOLD_RELEASE_GRACE_SECS
                    position = None
                    pos_question = ""
                    pos_debug = {}
                    pos_market_end_ts = 0
                    # Fall through — entry gate below will check slot_free_at_ts
                else:
                    current_bid = float(
                        pm.get("up_bid") if position.direction == "UP" else pm.get("down_bid") or 0.0
                    )
                    if current_bid <= 0:
                        continue
                    position.peak_bid = max(position.peak_bid, current_bid)
                    unrealized = current_bid - position.entry_price
                    seconds_left = int(snap.get("seconds_left") or 0)
                    time_held = ts - position.entry_time

                    exit_reason = ""

                    if strategy_name not in {"pm_btc_ml-entry", "pm_btc_ml-entry-v2", "math_smart"}:
                        if (
                            position.peak_bid >= position.entry_price + trailing_arm
                            and current_bid <= position.peak_bid - trailing_gap
                        ):
                            exit_reason = "trailing_stop"
                        elif unrealized >= take_profit_th:
                            exit_reason = "take_profit"
                        else:
                            stop_loss_gap = stop_loss_th * (0.75 if seconds_left <= 90 else 1.0)
                            is_ultra_cheap = position.entry_price <= _ULTRA_CHEAP_TAIL_PRICE
                            sl_delay = ultra_cheap_sl_delay if is_ultra_cheap else sl_arm_delay
                            sl_armed = time_held >= sl_delay
                            if current_bid <= position.entry_price - stop_loss_gap and sl_armed:
                                cp = float(btc.get("current_price") or 0.0)
                                bar_open = float(btc.get("bar_open") or 0.0)
                                btc_dist = math.log(cp / bar_open) if cp > 0 and bar_open > 0 else 0.0
                                adverse_move = btc_dist if position.direction == "DOWN" else -btc_dist
                                bid_collapse = current_bid <= position.entry_price - 2 * stop_loss_gap
                                gate_active = (
                                    adverse_move < sl_min_adverse
                                    and seconds_left > 60
                                    and not bid_collapse
                                )
                                if not gate_active:
                                    exit_reason = "stop_loss"

                    if not exit_reason:
                        ctx = self._build_strategy_context(
                            snap,
                            cash_amount=0.0,
                            prior_snapshots=prior_rows,
                        )
                        ctx.ml_p_up = _combined_ml_p_up(snap, seconds_left)
                        decision = strategy.evaluate_position(ctx, position, current_bid, ts)
                        if decision.exit_reason:
                            exit_reason = decision.exit_reason

                    if not exit_reason and strategy_name not in {"pm_btc_ml-entry", "pm_btc_ml-entry-v2", "math_smart"}:
                        if seconds_left <= 45 and unrealized <= -0.05:
                            exit_reason = "late_bar_cut"

                    if exit_reason:
                        exit_price = _exit_target(current_bid, exit_reason)
                        bar_outcome = _expiry_outcome(position.condition_id)
                        _record_trade(
                            position, ts, exit_reason, exit_price,
                            bar_outcome, pos_debug, pos_question,
                        )
                        if exit_reason == "stop_loss":
                            sl_reentry_guard[(cid, position.direction)] = position.entry_edge
                            market_sl_count[cid] = market_sl_count.get(cid, 0) + 1
                        slot_free_at_ts = ts
                        position = None
                        pos_question = ""
                        pos_debug = {}
                        pos_market_end_ts = 0
                    # While a position is open on the current market, do not
                    # also evaluate entries on the same tick.
                    continue

            # ---------- Entry path ----------
            if ts < slot_free_at_ts:
                continue

            seconds_left = int(snap.get("seconds_left") or 0)
            if seconds_left < min_seconds_left:
                continue

            staleness = feeds.get("staleness", {}) if isinstance(feeds, dict) else {}
            price_age = float(staleness.get("price_age") or 0.0)
            pm_up_age = float(staleness.get("pm_up_age") or 0.0)
            pm_down_age = float(staleness.get("pm_down_age") or 0.0)
            if max(price_age, pm_up_age, pm_down_age) > _FEED_STALE_SECS:
                continue

            ctx = self._build_strategy_context(
                snap,
                cash_amount=float(snap.get("cash_amount") or 0.0),
                prior_snapshots=prior_rows,
            )
            ctx.ml_p_up = _combined_ml_p_up(snap, seconds_left)
            signal = strategy.evaluate_entry(ctx)
            if signal.action == "NO_TRADE":
                confirm_condition_id = ""
                confirm_action = ""
                confirm_count = 0
                continue

            direction = "UP" if signal.action == "BUY_UP" else "DOWN"

            if market_sl_count.get(cid, 0) >= stop_loss_market_limit:
                continue
            guard = sl_reentry_guard.get((cid, direction))
            if guard is not None and float(signal.edge) < guard + _REENTRY_EDGE_PENALTY:
                continue

            if cid == confirm_condition_id and signal.action == confirm_action:
                confirm_count += 1
            else:
                confirm_condition_id = cid
                confirm_action = signal.action
                confirm_count = 1
            if confirm_count < entry_confirmation_ticks:
                continue

            entry_price = float(signal.price or 0.0)
            entry_shares = int(signal.size)
            if entry_shares <= 0 or entry_price <= 0:
                continue

            market_end_ts = int(snap.get("market_end_ts") or 0)
            position = Position(
                condition_id=cid,
                token_id="",
                direction=direction,
                shares=entry_shares,
                entry_price=entry_price,
                entry_time=ts,
                entry_edge=float(signal.edge),
                entry_p_up=float(signal.p_up),
                entry_seconds_left=seconds_left,
                peak_bid=entry_price,
            )
            pos_question = str(snap.get("question") or "")
            pos_debug = dict(signal.debug or {})
            pos_market_end_ts = market_end_ts

            if hold_to_expiry_default:
                bar_outcome = _expiry_outcome(cid)
                if bar_outcome:
                    won = direction == bar_outcome
                    exit_price = 1.0 if won else 0.0
                    _record_trade(
                        position, ts,
                        "expiry_win" if won else "expiry_loss",
                        exit_price, bar_outcome, pos_debug, pos_question,
                    )
                slot_free_at_ts = float(market_end_ts or ts) + _HOLD_RELEASE_GRACE_SECS
                position = None
                pos_question = ""
                pos_debug = {}
                pos_market_end_ts = 0

            confirm_condition_id = ""
            confirm_action = ""
            confirm_count = 0

        # If the bundle ended with a still-open position, settle at bar outcome
        # so replay trade count matches entry count.
        if position is not None:
            bar_outcome = _expiry_outcome(position.condition_id)
            if bar_outcome:
                won = position.direction == bar_outcome
                exit_price = 1.0 if won else 0.0
                _record_trade(
                    position, position.entry_time,
                    "expiry_win" if won else "expiry_loss",
                    exit_price, bar_outcome, pos_debug, pos_question,
                )

        return BundleBacktestResult(
            yaml_path=self.yaml_path,
            log_dir=log_dir,
            cfg=self.cfg,
            bars=bars,
            trades=trades,
        )

    def run(self, log_dir: str) -> BundleBacktestResult:
        """
        Canonical replay path.

        Replay reports should use the direct strategy runner so the code path
        matches the live bot's strategy implementation.
        """
        return self.run_direct_strategy(log_dir)

    def run_and_print(self, log_dir: str) -> BundleBacktestResult:
        result = self.run(log_dir)
        result.print_report()
        return result

    def run_direct_and_print(self, log_dir: str) -> BundleBacktestResult:
        result = self.run_direct_strategy(log_dir)
        result.print_report()
        return result

    def compare_to_real(self, log_dir: str, ignore_external_positions: bool = True) -> BundleBacktestComparison:
        return self.run_direct_strategy(log_dir).compare_to_real(ignore_external_positions=ignore_external_positions)

    def compare_hold_to_redemption(self, log_dir: str, ignore_external_positions: bool = True) -> RedemptionCounterfactual:
        return self.run(log_dir).compare_hold_to_redemption(ignore_external_positions=ignore_external_positions)


__all__ = [
    "BundleBacktestRunner",
    "BundleBacktestResult",
    "BundleBacktestComparison",
    "RedemptionCounterfactual",
]
