"""Funding-carry bot — main loop.

Long Kraken spot + short Hyperliquid perp, hold for the funding carry.
'Hold, don't time': open the basket, hold, with regime-flip protection +
deleverage-on-stress + delta-drift rebalance + a kill switch.

Run:  python3 main.py --config config.yaml
Start in dry_run: true and watch the logs for 1-2 weeks before going live.
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

from exchanges import HLOrderError, HyperliquidPerp, KrakenSpot, MarketData
from strategy import Cfg, CoinState, decide

HRS_YR = 24 * 365
log = logging.getLogger("funding-carry")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def load_cfg(path: str) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    # YAML 1.1 parses unquoted `0x...` as a hex integer, so an overlay that
    # forgets to quote the HL address/private key arrives here as `int`, not
    # `str`. Coerce back to a fixed-width 0x-prefixed hex string (preserving
    # leading zeros, which `int → hex` would otherwise drop).
    hl = cfg.setdefault("hyperliquid", {}) or {}
    cfg["hyperliquid"] = hl
    if isinstance(hl.get("account_address"), int):
        hl["account_address"] = f"0x{hl['account_address']:040x}"
    if isinstance(hl.get("secret_key"), int):
        hl["secret_key"] = f"0x{hl['secret_key']:064x}"
    if isinstance(hl.get("vault_address"), int):
        hl["vault_address"] = f"0x{hl['vault_address']:040x}"
    return cfg


# 0x + 40 hex chars (Ethereum address). HL account address + the API wallet's
# derived address are both this shape; the API wallet's PRIVATE KEY is 0x + 64.
_ADDR_RE = re.compile(r"0x[0-9a-fA-F]{40}")
_PRIVKEY_RE = re.compile(r"0x[0-9a-fA-F]{64}")


def validate_credentials(cfg: dict, *, dry_run: bool) -> None:
    """Fail fast on obviously-broken creds before the first loop.

    Blank fields are always OK (the bot mocks reads when creds are absent —
    useful for chart smoke-tests). Non-blank fields must look real:
      - hyperliquid.account_address : 0x + 40 hex chars (MASTER — the account
                                      that approved the API wallet)
      - hyperliquid.vault_address   : 0x + 40 hex chars (optional sub-account /
                                      vault to act on; blank = trade the master)
      - hyperliquid.secret_key       : 0x + 64 hex chars (API wallet, NOT main)
      - kraken.{api_key,api_secret}  : no "YOUR_" placeholder, length ≥ 20

    Pairing rules (key+secret together, or neither) are already enforced by
    exchanges.py when dry_run=False; this just makes the failure message
    clear before we hit HL/Kraken with junk and get a 422.
    """
    errs: list[str] = []
    hl = cfg.get("hyperliquid", {}) or {}
    kr = cfg.get("kraken", {}) or {}

    addr = (hl.get("account_address") or "").strip()
    if addr and not _ADDR_RE.fullmatch(addr):
        errs.append(
            f"hyperliquid.account_address looks invalid: {addr!r} — "
            "expected 0x + 40 hex chars (or empty)."
        )
    vault = (hl.get("vault_address") or "").strip()
    if vault and not _ADDR_RE.fullmatch(vault):
        errs.append(
            f"hyperliquid.vault_address looks invalid: {vault!r} — "
            "expected 0x + 40 hex chars (or empty). This is the sub-account / "
            "vault address; account_address must be the MASTER that approved "
            "the API wallet."
        )
    sk = (hl.get("secret_key") or "").strip()
    if sk and not _PRIVKEY_RE.fullmatch(sk):
        errs.append(
            "hyperliquid.secret_key looks invalid — expected 0x + 64 hex chars "
            "(or empty). Use an HL API wallet's private key, NOT your main key."
        )

    for k in ("api_key", "api_secret"):
        v = (kr.get(k) or "").strip()
        if not v:
            continue
        if "YOUR_" in v.upper():
            errs.append(f"kraken.{k} still contains the example placeholder ('YOUR_...').")
        elif len(v) < 20:
            errs.append(f"kraken.{k} is too short to be a real Kraken key ({len(v)} chars).")

    if errs:
        for e in errs:
            log.error("CONFIG: %s", e)
        log.error("Refusing to start. Fix the overlay (helm/bots/<name>.yaml) and redeploy.")
        raise SystemExit(2)

    if dry_run:
        log.info("config validated; dry_run=True — writes blocked, reads real (or mocked if blank).")
    else:
        log.warning("config validated; dry_run=False — REAL ORDERS WILL BE PLACED.")


class FundingWindow:
    """Tracks recent hourly funding per coin (refreshed from HL funding history)."""

    def __init__(self, md: MarketData, smooth_h: int, persist_h: int, exit_apr: float):
        self.md = md
        self.window_h = max(smooth_h, persist_h) + 4
        self.smooth_h = smooth_h
        self.persist_h = persist_h
        self.exit_apr = exit_apr
        self._cache: dict[str, list[float]] = {}
        self._last_fetch = 0.0

    def refresh(self, coins: list[str]) -> None:
        # funding updates hourly; refetch at most every ~10 min
        if time.time() - self._last_fetch < 600 and self._cache:
            return
        start_ms = int((time.time() - self.window_h * 3600) * 1000)
        for c in coins:
            try:
                rows = self.md.funding_history(c, start_ms)
                self._cache[c] = [float(r["fundingRate"]) for r in rows]
            except Exception as e:  # noqa: BLE001
                log.warning("funding_history %s failed: %s", c, e)
        self._last_fetch = time.time()

    def stats(self, coin: str, current_hourly: float) -> tuple[float, int]:
        """Return (smoothed_annualized, consecutive_recent_hours_at_or_below_exit_apr)."""
        hist = list(self._cache.get(coin, []))
        if current_hourly:
            hist.append(current_hourly)
        if not hist:
            return 0.0, 0
        sm = hist[-self.smooth_h:]
        smoothed_apr = (sum(sm) / len(sm)) * HRS_YR
        # count consecutive trailing hours whose own annualized rate <= exit_apr
        below = 0
        for r in reversed(hist):
            if r * HRS_YR <= self.exit_apr:
                below += 1
            else:
                break
        return smoothed_apr, below


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"regime_exited": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def execute(act: dict, *, hl: HyperliquidPerp, kr: KrakenSpot, mids: dict, state: dict,
            slippage_bps: float, perp_positions: dict, max_basis_open: float = 0.0030) -> None:
    coin = act["coin"]
    px = float(mids.get(coin, 0.0))
    slip = slippage_bps / 1e4
    kind = act["kind"]
    why = act.get("why", "")

    if kind == "mark_regime_exit":
        state.setdefault("regime_exited", {})[coin] = True
        log.warning("REGIME-EXIT %s — %s", coin, why)
        return
    if kind == "mark_regime_reentry":
        state.setdefault("regime_exited", {})[coin] = False
        log.info("REGIME-REENTRY %s — %s", coin, why)
        return
    if kind == "alert":
        log.warning("ALERT %s — %s", coin, why)
        return

    if px <= 0:
        log.error("no price for %s; skipping %s", coin, kind)
        return

    if kind == "open_pair":
        notional = float(act["notional"])
        lev = int(act.get("leverage", 0))
        log.info("OPEN %s notional≈$%.0f%s — %s", coin, notional,
                 f" L={lev}x" if lev > 0 else "", why)

        # Size BOTH legs to the same HL-rounded coin quantity so the hedge is exactly
        # delta-matched (HL rounds the short to its lot; the spot buy must match that lot,
        # not notional/px, or a small residual delta leaks in).
        sz = hl.round_size(coin, notional / px)
        if sz <= 0:
            log.error("ABORT open %s: size rounds to 0 (notional $%.2f @ %.4f)", coin, notional, px)
            return

        # Entry-basis gate: opening longs spot at the Kraken ASK and shorts the perp at the HL
        # mid, so the trade starts down by the cross-venue basis + spread. Read the real ask and
        # refuse to leg in when spot is too rich vs the perp — funding can't amortize a bad entry.
        try:
            kr_bid, kr_ask = kr.bbo(coin)
        except Exception as e:  # noqa: BLE001
            log.error("ABORT open %s: no Kraken quote — %s", coin, e)
            return
        basis = (kr_ask - px) / px if px > 0 else 0.0
        if basis > max_basis_open:
            log.warning("SKIP open %s: entry basis %.1fbps > %.1fbps cap "
                        "(kr_ask=%.6f hl_mid=%.6f) — would start underwater",
                        coin, basis * 1e4, max_basis_open * 1e4, kr_ask, px)
            return

        if lev > 0:  # idempotent on HL; auto-sizing sets leverage per-open
            try:
                hl.set_leverage(coin, lev)
            except Exception as e:  # noqa: BLE001
                log.warning("set_leverage %s=%dx before open failed: %s", coin, lev, e)

        # Leg-in order matters: short HL first (IOC), and only buy the spot hedge if it filled —
        # a rejected short must not leave a naked long.
        try:
            hl.open_short(coin, sz * px, px, limit_px=px * (1 - slip), tif="Ioc")
        except HLOrderError as e:
            log.error("ABORT open %s: HL short rejected, skipping Kraken buy — %s", coin, e)
            return
        # Hedge: MARKETABLE-LIMIT buy capped at ask*(1+slip) — fills against the book now but caps
        # the spread/slippage paid, instead of an uncapped market order. Same coin qty as the short.
        kr.buy(coin, sz, limit_px=kr_ask * (1 + slip))
        return

    if kind == "close_pair":
        emergency = act.get("emergency", False)
        log.warning("CLOSE %s%s — %s", coin, " [EMERGENCY]" if emergency else "", why)
        pos = perp_positions.get(coin)
        if pos:
            hl.close_short(coin, pos, limit_px=px * (1 + slip), tif="Ioc")
        amount = kr.balance(coin) or (act.get("spot_coins") or 0.0)
        if amount <= 0:
            return
        # Normal close: marketable-LIMIT sell capped at bid*(1-slip) to bound the spread paid on
        # the way out (symmetric to the entry). Emergency: MARKET — getting flat fast beats bps.
        if emergency:
            kr.sell(coin, amount)
        else:
            try:
                kr_bid, _ = kr.bbo(coin)
                kr.sell(coin, amount, limit_px=kr_bid * (1 - slip))
            except Exception as e:  # noqa: BLE001
                log.warning("quote failed closing %s, falling back to market sell — %s", coin, e)
                kr.sell(coin, amount)
        return

    if kind == "deleverage":
        reduce_notional = float(act["reduce_notional"])
        log.warning("DELEVERAGE %s reduce≈$%.0f — %s", coin, reduce_notional, why)
        sz = hl.round_size(coin, reduce_notional / px)  # match the spot cut to the perp lot
        hl.reduce_short(coin, sz * px, px, limit_px=px * (1 + slip), tif="Ioc")
        # MARKET sell: deleverage is risk reduction under margin stress — fill certainty trumps slippage.
        kr.sell(coin, sz)
        return

    if kind == "rebalance_spot":
        d = float(act["delta_notional"])  # >0 => buy spot, <0 => sell spot
        log.info("REBALANCE-SPOT %s %s≈$%.0f — %s", coin, "buy" if d > 0 else "sell", abs(d), why)
        try:
            kr_bid, kr_ask = kr.bbo(coin)
        except Exception:  # noqa: BLE001
            kr_bid = kr_ask = px
        if d > 0:
            kr.buy(coin, d / px, limit_px=kr_ask * (1 + slip))
        else:
            kr.sell(coin, -d / px, limit_px=kr_bid * (1 - slip))
        return

    log.error("unknown action kind: %s", kind)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.getenv("FC_CONFIG", "config.yaml"))
    ap.add_argument("--state-dir", default=os.getenv("FC_STATE_DIR", "."))
    ap.add_argument("--once", action="store_true", help="run a single loop iteration and exit")
    args = ap.parse_args()

    cfg = load_cfg(args.config)
    setup_logging(cfg.get("log_level", "INFO"))
    dry = bool(cfg.get("dry_run", True))
    log.info("=== funding-carry bot starting === dry_run=%s assets=%s",
             dry, [a["coin"] for a in cfg["assets"]])

    validate_credentials(cfg, dry_run=dry)

    hl_cfg, kr_cfg = cfg["hyperliquid"], cfg["kraken"]
    md = MarketData(hl_cfg["base_url"])
    hl = HyperliquidPerp(hl_cfg["base_url"], hl_cfg.get("account_address", ""),
                         hl_cfg.get("secret_key", ""),
                         vault_address=hl_cfg.get("vault_address", ""),
                         dry_run=dry)
    kr = KrakenSpot(kr_cfg.get("api_key", ""), kr_cfg.get("api_secret", ""),
                    quote=kr_cfg.get("quote", "USD"), dry_run=dry)

    sizing_mode = str(cfg.get("sizing_mode", "fixed")).lower()
    if sizing_mode not in ("fixed", "auto"):
        log.error("CONFIG: sizing_mode must be 'fixed' or 'auto', got %r", sizing_mode)
        raise SystemExit(2)
    # 0 = disabled (open all listed assets when funding turns positive).
    # >0 = sticky top-N: pick the N highest-smoothed-APR coins to OPEN; already-
    # open positions always stay selected (no churn-style rotation — that's
    # what the v1 backtest's threshold sweeps showed loses to always-hold).
    select_top_n = int(cfg.get("select_top_n", 0))

    scfg = Cfg(
        leverage=float(cfg.get("leverage", 2.0)),
        sizing_mode=sizing_mode,
        max_leverage=float(cfg.get("max_leverage", 3.0)),
        min_open_notional=float(cfg.get("min_open_notional", 25.0)),
        deleverage_liq_room=float(cfg.get("deleverage_liq_room", 0.15)),
        emergency_liq_room=float(cfg.get("emergency_liq_room", 0.05)),
        delta_rebalance_pct=float(cfg.get("delta_rebalance_pct", 0.08)),
        funding_exit_apr=float(cfg.get("funding_exit_apr", 0.0)),
        funding_exit_persist_hours=int(cfg.get("funding_exit_persist_hours", 48)),
        funding_reentry_apr=float(cfg.get("funding_reentry_apr", 0.03)),
    )
    fw = FundingWindow(md, int(cfg.get("funding_smooth_hours", 24)),
                       scfg.funding_exit_persist_hours, scfg.funding_exit_apr)
    state_path = Path(args.state_dir) / "fc_state.json"
    state = load_state(state_path)
    coins = [a["coin"] for a in cfg["assets"]]
    # In 'fixed' mode each coin has an explicit notional_usd. In 'auto' it's
    # ignored — the bot derives size from balances + weights at open time.
    targets = {a["coin"]: float(a.get("notional_usd", 0)) for a in cfg["assets"]}
    # Per-coin allocation weight for auto mode. Default = 1.0 each (equal split).
    weights = {a["coin"]: float(a.get("weight", 1.0)) for a in cfg["assets"]}
    # Optional per-coin max_leverage override (0 = use global cfg.max_leverage).
    max_lev_override = {a["coin"]: float(a.get("max_leverage", 0)) for a in cfg["assets"]}
    hl_margin_buffer = float(cfg.get("hl_margin_buffer", 0.20))
    spot_buffer_usd = float(cfg.get("spot_buffer_usd", 5.0))
    log.info("sizing_mode=%s%s", sizing_mode,
             (f" max_leverage={scfg.max_leverage} hl_margin_buffer={hl_margin_buffer:.0%} "
              f"spot_buffer=${spot_buffer_usd:.0f} weights={weights}") if sizing_mode == "auto"
             else f" leverage={scfg.leverage}x notionals={targets}")
    log.info("kraken quote=%s (spot pairs trade as COIN/%s)", kr.quote, kr.quote)
    if select_top_n > 0:
        log.info("select_top_n=%d (sticky: hold opens, refill empty slots from APR leaderboard)",
                 select_top_n)

    # In 'fixed' mode the leverage setting is static, so do it once at startup.
    # In 'auto' it's computed per-open and applied by execute() right before
    # the OPEN order; no startup call needed.
    if sizing_mode == "fixed":
        for c in coins:
            try:
                hl.set_leverage(c, int(scfg.leverage))
            except Exception as e:  # noqa: BLE001
                log.warning("set_leverage %s: %s", c, e)

    loop_s = int(cfg.get("loop_seconds", 60))
    max_errs = int(cfg.get("max_consecutive_errors", 10))
    basis_alert = float(cfg.get("max_basis_alert_bps", 50)) / 1e4
    consec_err = 0

    while True:
        t0 = time.time()
        try:
            fw.refresh(coins)
            mids = md.mids()
            funding_now = md.funding()
            perp_pos = hl.positions()
            acct_val = hl.account_value()
            kr_usd = kr.usd_balance()

            # Pre-compute smoothed funding for every coin (needed by both the
            # selection ranker and the per-coin processing below).
            smoothed_aprs: dict[str, float] = {}
            for c in coins:
                fh_c = float(funding_now.get(c, 0.0))
                sm_c, _ = fw.stats(c, fh_c)
                smoothed_aprs[c] = sm_c

            # Sticky top-N selection: coins with an open position stay in the
            # set; empty slots are filled by the highest-APR coins that aren't
            # currently regime-exited. select_top_n=0 disables (= all coins).
            has_position = {c for c in coins
                            if (p := perp_pos.get(c)) is not None and p.size != 0.0}
            regime_off = {c for c in coins
                          if bool(state.get("regime_exited", {}).get(c, False))}
            if select_top_n > 0:
                eligible = [c for c in coins if c not in has_position and c not in regime_off]
                eligible.sort(key=lambda c: smoothed_aprs.get(c, -1.0), reverse=True)
                new_picks = eligible[: max(0, select_top_n - len(has_position))]
                selected = has_position | set(new_picks)
            else:
                selected = set(coins) - regime_off  # legacy: all non-exited

            # Auto-sizing: each SELECTED coin gets a weighted slice of usable
            # balances; non-selected coins get 0 (decide() is skipped).
            total_w = sum(weights[c] for c in selected) or 1.0
            kr_usable = max(0.0, kr_usd - spot_buffer_usd)
            hl_usable = max(0.0, acct_val * (1.0 - hl_margin_buffer))
            kr_slice = {c: kr_usable * (weights[c] / total_w) if c in selected else 0.0
                        for c in coins}
            hl_slice = {c: hl_usable * (weights[c] / total_w) if c in selected else 0.0
                        for c in coins}

            snap = {"ts": int(t0),
                    "hl_account_value": round(acct_val, 2),
                    "kr_quote_balance": round(kr_usd, 2),
                    "kr_quote": kr.quote,
                    "coins": {}}
            for c in coins:
                px = float(mids.get(c, 0.0))
                fh = float(funding_now.get(c, 0.0))
                sm_apr, below_h = fw.stats(c, fh)
                pos = perp_pos.get(c)
                spot_coins = kr.balance(c)
                cs = CoinState(
                    coin=c, target_notional=targets[c], mark_px=px,
                    funding_hourly=fh, smoothed_funding_apr=sm_apr,
                    funding_below_exit_hours=below_h,
                    regime_exited=bool(state.get("regime_exited", {}).get(c, False)),
                    perp_size=pos.size if pos else 0.0,
                    perp_notional=pos.notional if pos else 0.0,
                    perp_liq_px=pos.liquidation_px if pos else 0.0,
                    spot_coins=spot_coins,
                    kr_usd_slice=kr_slice[c],
                    hl_margin_slice=hl_slice[c],
                    max_leverage_override=max_lev_override[c],
                )
                # NOTE: a precise perp/spot basis ("premium") would come from
                # meta_and_asset_ctxs (markPx vs oraclePx); for v1 we skip the
                # basis alert and rely on the close-only-on-your-terms discipline.
                # Non-selected coins (top-N watchlist losers, this loop) get
                # observed-only — no actions, just a STATE entry for visibility.
                if c in selected:
                    acts = decide(cs, scfg)
                    for a in acts:
                        if a["kind"] == "close_pair":
                            a["spot_coins"] = spot_coins
                        execute(a, hl=hl, kr=kr, mids=mids, state=state,
                                slippage_bps=float(cfg.get("hl_slippage_bps", 30)),
                                perp_positions=perp_pos,
                                max_basis_open=float(cfg.get("max_basis_open_bps", 30)) / 1e4)
                else:
                    acts = []
                snap["coins"][c] = {
                    "px": px, "funding_hr_bps": round(fh * 1e4, 3),
                    "funding_apr": round(sm_apr, 4), "below_exit_h": below_h,
                    "perp_notional": round(cs.perp_notional, 1),
                    "spot_notional": round(cs.spot_notional, 1),
                    "delta": round(cs.spot_notional - cs.perp_notional, 1),
                    "liq_room": round(cs.liq_room_frac, 3),
                    "regime_exited": cs.regime_exited,
                    "selected": c in selected,
                    "n_actions": len(acts),
                }
            save_state(state_path, state)
            log.info("STATE %s", json.dumps(snap))
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
                    for c in coins:
                        pos = hl.positions().get(c)
                        px = float(md.mids().get(c, 0.0)) or 1.0
                        if pos:
                            hl.close_short(c, pos, limit_px=px * 1.02, tif="Ioc")
                        bal = kr.balance(c)
                        if bal:
                            kr.sell(c, bal)
                except Exception:  # noqa: BLE001
                    log.exception("flatten failed")
                return 1
        if args.once:
            return 0
        dt = time.time() - t0
        time.sleep(max(1.0, loop_s - dt))


if __name__ == "__main__":
    sys.exit(main())
