"""5-minute mean-reversion runner — ONE code path, paper or live via a flag (experiment #24).

The signal, the order decision, the accounting, and the logging are identical in paper and live; the
ONLY thing that changes is the BROKER — whether a maker fill is *simulated* or *sent to Binance*. This
is deliberate: the point of paper-trading is to predict live, which only holds if paper runs the live
code. (Same principle as the repo's NFR1 "one weight path, backtest == paper".)

  --paper  (default)  PaperBroker — simulates the maker fill from the next bar's range. No keys.
  --live              LiveBroker  — posts a real post-only (maker) limit via Binance fapi with your
                      API keys, reconciles actual fills. GUARDED: needs --live AND BINANCE_API_KEY/SECRET
                      AND --i-understand-live; a --max-loss kill-switch halts + flattens on cumulative loss.

Strategy: fade the z-score (enter |z|>entry, hold, exit |z|<exit) on BTC 5m. Maker limit posted at the
signal bar's close; on BTC the spread is ~0.015bp so the maker benefit is the lower FEE, not spread.

Usage:
  python scripts/run_5m_meanrev.py --state-dir ./state/paper_5m                 # paper loop
  python scripts/run_5m_meanrev.py --once --state-dir ./state/paper_5m          # one bar (cron/smoke)
  python scripts/run_5m_meanrev.py --live --notional 200 --max-loss 50 --i-understand-live   # real $
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PPY_5M = 365 * 24 * 12
FAPI = "https://fapi.binance.com"


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}  {msg}", flush=True)


# --------------------------------------------------------------------------- data + signal
def fetch_klines(symbol: str, interval: str, limit: int) -> list[dict]:
    url = f"{FAPI}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "atb-5m"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.loads(r.read())
    now_ms = time.time() * 1000
    return [{"open_time": k[0], "high": float(k[2]), "low": float(k[3]), "close": float(k[4]),
             "close_time": k[6]} for k in rows if k[6] < now_ms]   # closed bars only


def zscore(closes: np.ndarray, n: int) -> float:
    if len(closes) < n + 1:
        return 0.0
    w = closes[-n:]
    sd = w.std(ddof=1)
    return float((closes[-1] - w.mean()) / sd) if sd > 0 else 0.0


def target_from_signal(pos, z, lev, entry, exit_):
    if pos == 0.0:
        return -lev if z > entry else (lev if z < -entry else 0.0)
    return 0.0 if abs(z) < exit_ else pos          # hold until reversion, then flat


# --------------------------------------------------------------------------- brokers
class PaperBroker:
    """Simulate a maker fill: the limit posted last bar fills iff THIS bar's range reaches it."""
    live = False

    def __init__(self, fee_bps: float):
        self.fee = fee_bps / 1e4

    def settle(self, pos, pending_target, pending_limit, bar) -> dict:
        delta = pending_target - pos
        if abs(delta) < 1e-12 or pending_limit is None:
            return {"new_pos": pos, "posted": False, "filled": False, "fee_cost": 0.0}
        touched = (bar["low"] <= pending_limit) if delta > 0 else (bar["high"] >= pending_limit)
        if touched:
            return {"new_pos": pending_target, "posted": True, "filled": True,
                    "fee_cost": self.fee * abs(delta)}
        return {"new_pos": pos, "posted": True, "filled": False, "fee_cost": 0.0}

    def arm(self, target, limit_price):              # paper: nothing to place; runner holds the pending
        return


class LiveBroker:
    """Place a real POST-ONLY (maker) limit on Binance USDS-M futures and reconcile actual fills.

    GUARDED + UNEXERCISED until the first real run. Position size = `notional` USD. Reconciliation reads
    the actual position each bar; the runner accounts P&L off the real fills, so paper and live share the
    SAME math. Validate with tiny size + the kill-switch the day you flip --live on.
    """
    live = True

    def __init__(self, fee_bps: float, symbol: str, notional: float):
        self.fee = fee_bps / 1e4
        self.symbol = symbol
        self.notional = notional
        self.key = os.environ["BINANCE_API_KEY"]
        self.secret = os.environ["BINANCE_API_SECRET"].encode()
        self.step = self._symbol_step()

    def _signed(self, method, path, params):
        params["timestamp"] = int(time.time() * 1000)
        qs = urllib.parse.urlencode(params)
        sig = hmac.new(self.secret, qs.encode(), hashlib.sha256).hexdigest()
        url = f"{FAPI}{path}?{qs}&signature={sig}"
        req = urllib.request.Request(url, method=method, headers={"X-MBX-APIKEY": self.key})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def _symbol_step(self):
        info = json.loads(urllib.request.urlopen(f"{FAPI}/fapi/v1/exchangeInfo", timeout=20).read())
        s = next(x for x in info["symbols"] if x["symbol"] == self.symbol)
        lot = next(f for f in s["filters"] if f["filterType"] == "LOT_SIZE")
        return float(lot["stepSize"])

    def _actual_pos_units(self):                     # signed position size in equity-leverage units
        risk = self._signed("GET", "/fapi/v2/positionRisk", {"symbol": self.symbol})
        amt = float(risk[0]["positionAmt"]) if risk else 0.0
        return amt

    def settle(self, pos, pending_target, pending_limit, bar) -> dict:
        # reconcile: did the resting order fill? (compare actual exchange position to expectation)
        amt = self._actual_pos_units()
        px = bar["close"]
        cur_lev = (amt * px) / self.notional if self.notional else 0.0      # → {−L,0,+L}-ish
        new_pos = round(cur_lev)
        filled = abs(new_pos - pos) > 1e-9
        return {"new_pos": float(new_pos), "posted": pending_target != pos, "filled": filled,
                "fee_cost": self.fee * abs(new_pos - pos) if filled else 0.0}

    def arm(self, target, limit_price):
        """Cancel any resting order, then post a fresh post-only limit toward `target`."""
        try:
            self._signed("DELETE", "/fapi/v1/allOpenOrders", {"symbol": self.symbol})
        except Exception:
            pass
        if target == 0.0:                            # exit → reduce-only opposite of current handled by qty sign
            pass
        qty = round((abs(target) * self.notional / limit_price) / self.step) * self.step
        if qty <= 0:
            return
        side = "BUY" if target > 0 else "SELL"
        self._signed("POST", "/fapi/v1/order", {
            "symbol": self.symbol, "side": side, "type": "LIMIT", "timeInForce": "GTX",  # GTX = post-only
            "quantity": qty, "price": f"{limit_price:.1f}", "reduceOnly": "false"})


# --------------------------------------------------------------------------- state + runner
def load_state(p: Path) -> dict:
    if p.exists():
        return json.loads(p.read_text())
    return {"pos": 0.0, "last_open_time": None, "last_close": None, "pending_target": 0.0,
            "pending_limit": None, "rets_net": [], "rets_gross": [], "orders_posted": 0,
            "orders_filled": 0, "wins": 0, "closed_trades": 0, "fees_paid": 0.0,
            "entry_equity": None, "start_ts": None, "last_ts": None, "equity_net": 1.0,
            "equity_gross": 1.0, "hwm": 1.0, "max_dd": 0.0, "halted": False}


def summarize(st: dict) -> dict:
    rn, rg = np.array(st["rets_net"], float), np.array(st["rets_gross"], float)
    sh = lambda r: float(r.mean() / r.std(ddof=1) * np.sqrt(PPY_5M)) if r.size > 2 and r.std(ddof=1) > 0 else 0.0
    return {"bars": len(rn), "start_ts": st["start_ts"], "last_ts": st["last_ts"],
            "equity_net": round(st["equity_net"], 6), "equity_gross": round(st["equity_gross"], 6),
            "cum_ret_net": round(st["equity_net"] - 1, 6), "cum_ret_gross": round(st["equity_gross"] - 1, 6),
            "sharpe_net": round(sh(rn), 3), "sharpe_gross": round(sh(rg), 3), "max_dd": round(st["max_dd"], 6),
            "fees_paid_frac": round(st["fees_paid"], 6), "orders_posted": st["orders_posted"],
            "orders_filled": st["orders_filled"],
            "fill_rate": round(st["orders_filled"] / st["orders_posted"], 3) if st["orders_posted"] else None,
            "closed_trades": st["closed_trades"],
            "win_rate": round(st["wins"] / st["closed_trades"], 3) if st["closed_trades"] else None,
            "halted": st["halted"], "position": st["pos"]}


def step(args, broker, st, closes, bar) -> bool:
    if st["last_open_time"] == bar["open_time"]:
        return False
    price = bar["close"]
    ret = (price / st["last_close"] - 1.0) if st["last_close"] else 0.0
    pos = st["pos"]

    res = broker.settle(pos, st["pending_target"], st["pending_limit"], bar)
    if res["posted"]:
        st["orders_posted"] += 1
    if res["filled"]:
        st["orders_filled"] += 1
    bar_pos, fee_cost = res["new_pos"], res["fee_cost"]

    st["equity_gross"] *= (1.0 + bar_pos * ret)
    st["equity_net"] *= (1.0 + bar_pos * ret) * (1.0 - fee_cost)
    st["rets_gross"].append(bar_pos * ret)
    st["rets_net"].append(bar_pos * ret - fee_cost)
    st["fees_paid"] += fee_cost
    if res["filled"]:
        if pos == 0.0 and bar_pos != 0.0:
            st["entry_equity"] = st["equity_net"]
        elif bar_pos == 0.0 and pos != 0.0:
            st["closed_trades"] += 1
            st["wins"] += int(bool(st["entry_equity"] and st["equity_net"] > st["entry_equity"]))
    pos = bar_pos

    # kill-switch (live): halt + flatten on cumulative loss past --max-loss (as a fraction of notional)
    if broker.live and args.max_loss and (1.0 - st["equity_net"]) * getattr(broker, "notional", 0) >= args.max_loss:
        st["halted"] = True

    z = zscore(closes, args.lookback)
    tgt = 0.0 if st["halted"] else target_from_signal(pos, z, args.leverage, args.entry, args.exit)
    st["pending_target"], st["pending_limit"] = tgt, price
    broker.arm(tgt, price)

    st.update(pos=pos, last_open_time=bar["open_time"], last_close=price,
              last_ts=datetime.fromtimestamp(bar["close_time"] / 1000, tz=timezone.utc).isoformat())
    st["start_ts"] = st["start_ts"] or st["last_ts"]
    st["hwm"] = max(st["hwm"], st["equity_net"])
    dd = st["equity_net"] / st["hwm"] - 1.0
    st["max_dd"] = min(st["max_dd"], dd)
    tag = "FILLED" if res["filled"] else ("missed" if res["posted"] else "—")
    halt = "  [HALTED]" if st["halted"] else ""
    log(f"bar {st['last_ts']}  px {price:,.1f}  z {z:+.2f}  pos {pos:+.0f}  order[{tag}] ->tgt {tgt:+.0f}  "
        f"ret {bar_pos*ret:+.4%}  fee {fee_cost:.4%}  eqNet {st['equity_net']:.4f} "
        f"eqGross {st['equity_gross']:.4f}  dd {dd:+.2%}{halt}")
    return True


def write_logs(d: Path, st: dict) -> None:
    (d / "book.json").write_text(json.dumps(st))
    (d / "summary.json").write_text(json.dumps(summarize(st), indent=2))
    with (d / "audit.jsonl").open("a") as f:
        f.write(json.dumps({"ts": st["last_ts"], "px": st["last_close"], "pos": st["pos"],
                            "equity_net": st["equity_net"], "equity_gross": st["equity_gross"]}) + "\n")


def run_once(args, broker, d: Path) -> bool:
    st = load_state(d / "book.json")
    bars = fetch_klines(args.symbol, args.interval, args.lookback + 60)
    if len(bars) < args.lookback + 2:
        log(f"warming up: {len(bars)}/{args.lookback + 2} bars"); return False
    closes = np.array([b["close"] for b in bars], float)
    if step(args, broker, st, closes, bars[-1]):
        write_logs(d, st)
        s = summarize(st)
        log(f"SUMMARY  bars {s['bars']}  netRet {s['cum_ret_net']:+.3%}(Sh {s['sharpe_net']})  "
            f"grossRet {s['cum_ret_gross']:+.3%}(Sh {s['sharpe_gross']})  maxDD {s['max_dd']:.2%}  "
            f"fees {s['fees_paid_frac']:.3%}  fills {s['orders_filled']}/{s['orders_posted']}({s['fill_rate']})  "
            f"win {s['win_rate']}  {'HALTED' if s['halted'] else ''}")
        return True
    log("no new closed bar — idempotent"); return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="./state/paper_5m")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--lookback", type=int, default=48)
    ap.add_argument("--entry", type=float, default=2.0)
    ap.add_argument("--exit", type=float, default=0.5)
    ap.add_argument("--leverage", type=float, default=1.0)
    ap.add_argument("--fee-bps", type=float, default=2.0, help="MAKER fee/fill (VIP0=2.0; BNB burn=1.8)")
    ap.add_argument("--live", action="store_true", help="place REAL maker orders (else paper-simulate)")
    ap.add_argument("--notional", type=float, default=0.0, help="live: USD position size")
    ap.add_argument("--max-loss", type=float, default=0.0, help="live: halt+flatten after this USD loss")
    ap.add_argument("--i-understand-live", action="store_true", help="required to arm --live")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    d = Path(args.state_dir); d.mkdir(parents=True, exist_ok=True)

    if args.live:
        if not (args.i_understand_live and args.notional > 0 and args.max_loss > 0):
            log("REFUSING --live without --i-understand-live AND --notional>0 AND --max-loss>0"); return 2
        broker = LiveBroker(args.fee_bps, args.symbol, args.notional)
        log(f"*** LIVE TRADING *** notional ${args.notional} kill-switch ${args.max_loss}")
    else:
        broker = PaperBroker(args.fee_bps)
    log(f"5m MR runner [{'LIVE' if broker.live else 'PAPER'}/maker] | {args.symbol} {args.interval} | "
        f"lb {args.lookback} entry>{args.entry} exit<{args.exit} | lev {args.leverage} fee {args.fee_bps}bp | {d}")

    if args.once:
        run_once(args, broker, d); return 0
    while True:
        try:
            run_once(args, broker, d)
        except Exception as e:
            log(f"ERROR {e!r} — retry next cycle")
        now = time.time()
        time.sleep(max(5.0, (now // 300 + 1) * 300 + 15 - now))


if __name__ == "__main__":
    sys.exit(main())
