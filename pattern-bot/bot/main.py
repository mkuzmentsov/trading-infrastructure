"""Pattern trading bot — main loop.

Scans candles for double top / double bottom patterns; on a confirmed neckline
break it REPORTS to the console and opens a trade (measured-move target + stop).
Trades Hyperliquid perps now; swap `exchange:` in config to move venues later.

Run:  python3 main.py --config config.yaml [--once]
Start in dry_run: true and watch the console for a while before going live.

Console lines you'll see:
  PATTERN double_bottom BTC: neckline=… height=… → CONFIRMED @ close=…
  OPEN LONG BTC sz=… entry=… stop=… target=… RR=…
  CLOSE BTC reason=target_hit pnl=$… (R=…)
  STATE {…}   (per-loop snapshot per coin)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import yaml

from broker import Broker, BrokerPosition, OrderError, make_broker
from patterns import PatternCfg, detect
from strategy import Position, RiskCfg, decide

log = logging.getLogger("pattern-bot")

_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000,
}


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def load_cfg(path: str) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    # YAML 1.1 parses unquoted 0x… as a hex int — coerce HL creds back to fixed-
    # width hex strings (same guard as funding-carry).
    hl = cfg.setdefault("hyperliquid", {}) or {}
    cfg["hyperliquid"] = hl
    if isinstance(hl.get("account_address"), int):
        hl["account_address"] = f"0x{hl['account_address']:040x}"
    if isinstance(hl.get("secret_key"), int):
        hl["secret_key"] = f"0x{hl['secret_key']:064x}"
    if isinstance(hl.get("vault_address"), int):
        hl["vault_address"] = f"0x{hl['vault_address']:040x}"
    return cfg


_ADDR_RE = re.compile(r"0x[0-9a-fA-F]{40}")
_PRIVKEY_RE = re.compile(r"0x[0-9a-fA-F]{64}")


def validate_credentials(cfg: dict, *, dry_run: bool) -> None:
    """Fail fast on obviously-broken creds before the first loop. Blank is OK
    (the bot reads public data + paper-trades). Only the HL path is validated;
    Kraken Futures is added when that broker lands."""
    if str(cfg.get("exchange", "hyperliquid")).lower() != "hyperliquid":
        return
    errs: list[str] = []
    hl = cfg.get("hyperliquid", {}) or {}
    addr = (hl.get("account_address") or "").strip()
    if addr and not _ADDR_RE.fullmatch(addr):
        errs.append(f"hyperliquid.account_address invalid: {addr!r} — expected 0x + 40 hex (or empty).")
    vault = (hl.get("vault_address") or "").strip()
    if vault and not _ADDR_RE.fullmatch(vault):
        errs.append(f"hyperliquid.vault_address invalid: {vault!r} — expected 0x + 40 hex (or empty).")
    sk = (hl.get("secret_key") or "").strip()
    if sk and not _PRIVKEY_RE.fullmatch(sk):
        errs.append("hyperliquid.secret_key invalid — expected 0x + 64 hex (API wallet key, not your main key).")
    if errs:
        for e in errs:
            log.error("CONFIG: %s", e)
        log.error("Refusing to start. Fix the config and restart.")
        raise SystemExit(2)
    if dry_run:
        log.info("config validated; dry_run=True — writes blocked, public data read (paper-trades).")
    else:
        log.warning("config validated; dry_run=False — REAL ORDERS WILL BE PLACED.")


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"coins": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def _pos_from_state(d: dict | None) -> Position | None:
    if not d:
        return None
    return Position(
        coin=d["coin"], side=d["side"], size=float(d["size"]),
        entry_px=float(d["entry_px"]), stop_px=float(d["stop_px"]),
        target_px=float(d["target_px"]), confirm_time=int(d["confirm_time"]),
        opened_time=int(d.get("opened_time", 0)), bars_held=int(d.get("bars_held", 0)),
    )


def _pos_to_state(p: Position) -> dict:
    return {"coin": p.coin, "side": p.side, "size": p.size, "entry_px": p.entry_px,
            "stop_px": p.stop_px, "target_px": p.target_px, "confirm_time": p.confirm_time,
            "opened_time": p.opened_time, "bars_held": p.bars_held}


def process_coin(coin: str, broker: Broker, pcfg: PatternCfg, rcfg: RiskCfg,
                 interval: str, lookback: int, equity: float,
                 cstate: dict, live: bool, live_pos: BrokerPosition | None) -> dict:
    """Run one coin: detect → decide → execute. Mutates and returns cstate
    (last_confirm_time + tracked trade). Logs PATTERN/OPEN/CLOSE lines."""
    candles = broker.candles(coin, interval, lookback)
    if len(candles) < 2 * pcfg.pivot_lookback + pcfg.min_bars_between + 2:
        log.warning("%s: only %d candles, need more for detection — skipping", coin, len(candles))
        return cstate
    mark = broker.mark_px(coin) or candles[-1]["close"]
    last_close_t = candles[-1]["time"]
    ms = _INTERVAL_MS.get(interval, 3_600_000)

    pos = _pos_from_state(cstate.get("trade"))
    # Reconcile: if live and the exchange shows the position is gone (closed
    # elsewhere / stopped out manually), drop our tracked trade.
    if pos is not None and live and live_pos is None:
        log.warning("%s: tracked %s trade no longer on exchange — clearing local state", coin, pos.side)
        pos = None
        cstate["trade"] = None
    # Recompute bars held from candle times (restart-safe).
    if pos is not None and pos.opened_time:
        pos.bars_held = max(0, int((last_close_t - pos.opened_time) / ms))

    signal = detect(candles, pcfg, coin=coin)
    last_ct = cstate.get("last_confirm_time")
    if signal is not None and signal.confirm_time != last_ct:
        log.info("PATTERN %s %s: neckline=%.6g extreme=%.6g height=%.6g → CONFIRMED @ close=%.6g",
                 signal.kind, coin, signal.neckline, signal.extreme_level,
                 signal.height, signal.entry_ref)

    acts = decide(signal, pos, equity, mark, last_ct, rcfg)
    for a in acts:
        kind = a["kind"]
        if kind == "open_trade":
            log.info("OPEN %s %s sz=%.6g entry=%.6g stop=%.6g target=%.6g RR=%.2f — %s",
                     a["side"].upper(), coin, a["size"], a["entry"], a["stop"],
                     a["target"], a["rr"], a["why"])
            try:
                broker.open_market(coin, a["side"], a["size"])
            except OrderError as e:
                log.error("OPEN %s rejected — not recording trade: %s", coin, e)
                cstate["last_confirm_time"] = a["confirm_time"]  # don't retry the same break
                continue
            new_pos = Position(coin=coin, side=a["side"], size=a["size"], entry_px=a["entry"],
                               stop_px=a["stop"], target_px=a["target"],
                               confirm_time=a["confirm_time"], opened_time=last_close_t, bars_held=0)
            cstate["trade"] = _pos_to_state(new_pos)
            cstate["last_confirm_time"] = a["confirm_time"]
        elif kind == "close_trade" and pos is not None:
            gross = (mark - pos.entry_px) if pos.side == "long" else (pos.entry_px - mark)
            pnl = gross * pos.size
            r = pnl / (abs(pos.entry_px - pos.stop_px) * pos.size) if pos.entry_px != pos.stop_px else 0.0
            log.info("CLOSE %s reason=%s pnl=$%.2f (R=%.2f) — %s",
                     coin, a["reason"], pnl, r, a["why"])
            try:
                bp = live_pos or BrokerPosition(coin=coin, side=pos.side, size=pos.size,
                                                entry_px=pos.entry_px, mark_px=mark)
                broker.close(coin, bp)
            except OrderError as e:
                log.error("CLOSE %s rejected — keeping tracked trade, will retry: %s", coin, e)
                continue
            cstate["trade"] = None
        elif kind == "alert":
            log.warning("ALERT %s — %s", coin, a["why"])
            cstate["last_confirm_time"] = signal.confirm_time if signal else last_ct

    # STATE snapshot
    tp = cstate.get("trade")
    log.info("STATE %s", json.dumps({
        "coin": coin, "mark": round(mark, 6), "bar": last_close_t,
        "in_position": tp is not None,
        "pos": ({"side": tp["side"], "entry": round(tp["entry_px"], 6),
                 "stop": round(tp["stop_px"], 6), "target": round(tp["target_px"], 6),
                 "bars_held": pos.bars_held if pos else 0} if tp else None),
        "last_signal": cstate.get("last_confirm_time"),
    }))
    return cstate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.getenv("PB_CONFIG", "config.yaml"))
    ap.add_argument("--state-dir", default=os.getenv("PB_STATE_DIR", "."))
    ap.add_argument("--once", action="store_true", help="run a single loop iteration and exit")
    args = ap.parse_args()

    cfg = load_cfg(args.config)
    setup_logging(cfg.get("log_level", "INFO"))
    dry = bool(cfg.get("dry_run", True))
    coins = [c.strip().upper() for c in cfg.get("coins", ["BTC"])]
    interval = str(cfg.get("interval", "1h"))
    lookback = int(cfg.get("candle_lookback", 400))
    log.info("=== pattern bot starting === exchange=%s dry_run=%s coins=%s interval=%s",
             cfg.get("exchange", "hyperliquid"), dry, coins, interval)

    validate_credentials(cfg, dry_run=dry)
    pcfg = PatternCfg.from_dict(cfg.get("pattern", {}))
    rcfg = RiskCfg.from_dict(cfg.get("risk", {}))
    broker = make_broker(cfg)

    paper_equity = float(cfg.get("paper_equity", 10_000.0))
    state_path = Path(args.state_dir) / "pattern_state.json"
    state = load_state(state_path)
    state.setdefault("coins", {})

    # Set leverage once at startup so HL margin matches our notional cap.
    for c in coins:
        try:
            broker.set_leverage(c, max(1, int(rcfg.max_leverage)))
        except Exception as e:  # noqa: BLE001
            log.warning("set_leverage %s: %s", c, e)

    loop_s = int(cfg.get("loop_seconds", 60))
    max_errs = int(cfg.get("max_consecutive_errors", 10))
    consec_err = 0

    while True:
        t0 = time.time()
        try:
            live = not dry
            eq = broker.equity()
            equity = eq if eq > 0 else paper_equity
            live_positions = broker.positions() if live else {}
            for c in coins:
                cstate = state["coins"].setdefault(c, {"last_confirm_time": None, "trade": None})
                state["coins"][c] = process_coin(
                    c, broker, pcfg, rcfg, interval, lookback, equity,
                    cstate, live, live_positions.get(c))
            save_state(state_path, state)
            consec_err = 0
        except KeyboardInterrupt:
            log.info("interrupted; exiting")
            return 0
        except Exception as e:  # noqa: BLE001
            consec_err += 1
            log.exception("loop error (%d/%d): %s", consec_err, max_errs, e)
            if consec_err >= max_errs:
                log.error("KILL SWITCH: %d consecutive errors. Attempting to flatten all positions.", consec_err)
                try:
                    for c, bp in (broker.positions() if not dry else {}).items():
                        broker.close(c, bp)
                        state["coins"].get(c, {})["trade"] = None
                    save_state(state_path, state)
                except Exception:  # noqa: BLE001
                    log.exception("flatten failed")
                return 1
        if args.once:
            return 0
        dt = time.time() - t0
        time.sleep(max(1.0, loop_s - dt))


if __name__ == "__main__":
    sys.exit(main())
