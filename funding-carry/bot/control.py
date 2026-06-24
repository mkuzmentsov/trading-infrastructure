"""fc_control — manual pause / resume / exit for a running funding-carry bot.

Run INSIDE the pod (shares the main loop's filesystem + config):
    kubectl exec deploy/fc-top1-200 -n funding-carry -- python /app/bot/control.py <cmd>

Commands:
  status   show the pause flag + live HL/Kraken positions.
  pause    stop opening/managing — the loop goes monitor-only. Positions untouched.
  resume   clear the pause flag — the loop resumes trading next iteration.
  exit     FLATTEN everything (close HL shorts + unstake & sell Kraken spot) AND
           pause, so the loop can't re-open. Use this as the panic button.

The pause flag is a file (FC_PAUSE_FILE, default /tmp/fc_pause) on the EPHEMERAL
container filesystem — by design it does NOT persist across pod restarts /
redeploys. A fresh deploy always comes up trading-enabled; to make a pause stick,
re-run `pause` after the deploy (or just don't redeploy while paused).

Honors config dry_run: with dry_run:true, `exit` logs intended orders but places
none (safe to rehearse).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from exchanges import HLOrderError, HyperliquidPerp, KrakenSpot, MarketData
from main import load_cfg, setup_logging

log = logging.getLogger("fc-control")


def pause_path() -> str:
    return os.getenv("FC_PAUSE_FILE", "/tmp/fc_pause")


def build(cfg: dict):
    dry = bool(cfg.get("dry_run", True))
    hl_cfg, kr_cfg = cfg["hyperliquid"], cfg["kraken"]
    md = MarketData(hl_cfg["base_url"])
    hl = HyperliquidPerp(hl_cfg["base_url"], hl_cfg.get("account_address", ""),
                         hl_cfg.get("secret_key", ""),
                         vault_address=hl_cfg.get("vault_address", ""), dry_run=dry)
    kr = KrakenSpot(kr_cfg.get("api_key", ""), kr_cfg.get("api_secret", ""),
                    quote=kr_cfg.get("quote", "USD"), dry_run=dry,
                    earn_enabled=bool(cfg.get("earn_enabled", False)),
                    earn_flex_only=bool(cfg.get("earn_flex_only", True)),
                    earn_min_wallet_frac=float(cfg.get("earn_min_wallet_frac", 0.05)))
    return md, hl, kr, dry


def do_status(cfg: dict) -> int:
    md, hl, kr, dry = build(cfg)
    pf = pause_path()
    print(f"pause flag: {pf} -> {'PRESENT (trading disabled)' if os.path.exists(pf) else 'absent (trading enabled)'}")
    print(f"dry_run: {dry}")
    coins = [a["coin"] for a in cfg["assets"]]
    mids = md.mids()
    pos = hl.positions()
    print("HL positions:")
    any_p = False
    for c in coins:
        p = pos.get(c)
        if p and p.size != 0.0:
            any_p = True
            print(f"  {c}: size={p.size} notional=${p.notional:.0f} liq={p.liquidation_px} uPnL=${p.unrealized_pnl:.2f}")
    if not any_p:
        print("  (none)")
    print("Kraken holdings (total incl. staking):")
    for c in coins:
        bal = kr.balance(c)
        if bal and bal * float(mids.get(c, 0) or 0) > 1:
            print(f"  {c}: {bal} (~${bal * float(mids.get(c,0) or 0):.0f}) wallet={kr.wallet_balance(c)}")
    print(f"Kraken {kr.quote}: {kr.usd_balance():.2f}")
    return 0


def do_pause(cfg: dict) -> int:
    pf = pause_path()
    with open(pf, "w") as f:
        f.write("paused by control.py\n")
    log.warning("PAUSED — wrote %s. The loop will go monitor-only within one cycle.", pf)
    return 0


def do_resume(cfg: dict) -> int:
    pf = pause_path()
    if os.path.exists(pf):
        os.remove(pf)
        log.info("RESUMED — removed %s. The loop resumes trading next cycle.", pf)
    else:
        log.info("not paused (%s absent); nothing to do.", pf)
    return 0


def do_exit(cfg: dict) -> int:
    # Pause FIRST so the main loop stops acting, then flatten ourselves.
    do_pause(cfg)
    md, hl, kr, dry = build(cfg)
    coins = [a["coin"] for a in cfg["assets"]]
    mids = md.mids()
    log.warning("EXIT: flattening all positions (dry_run=%s)", dry)
    errs = 0
    for c in coins:
        px = float(mids.get(c, 0.0)) or 0.0
        try:
            pos = hl.positions().get(c)
            if pos and pos.size != 0.0:
                ref = px or pos.mark_px or 1.0
                hl.close_short(c, pos, limit_px=ref * 1.02, tif="Ioc")
        except HLOrderError as e:  # noqa: BLE001
            errs += 1
            log.error("close HL short %s failed: %s", c, e)
        try:
            bal = kr.balance(c)  # total incl. staking; sell() unstakes first
            if px and bal * px > 1.0:  # skip dust
                kr.sell(c, bal)
        except Exception as e:  # noqa: BLE001
            errs += 1
            log.error("sell Kraken %s failed: %s", c, e)
    log.warning("EXIT done (%d errors). Bot remains PAUSED (%s). Verify with: status",
                errs, pause_path())
    return 1 if errs else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="manual control for the funding-carry bot")
    ap.add_argument("command", choices=["status", "pause", "resume", "exit"])
    ap.add_argument("--config", default=os.getenv("FC_CONFIG", "/app/config/config.yaml"))
    args = ap.parse_args()
    cfg = load_cfg(args.config)
    setup_logging(cfg.get("log_level", "INFO"))
    return {"status": do_status, "pause": do_pause,
            "resume": do_resume, "exit": do_exit}[args.command](cfg)


if __name__ == "__main__":
    sys.exit(main())
