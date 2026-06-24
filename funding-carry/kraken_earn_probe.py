#!/usr/bin/env python3
"""Kraken Earn probe — validate the live Earn API before enabling it in the bot.

Reads your Kraken keys from the bot config (read-only calls; it never allocates
or trades), then prints:
  1. FLEX (instant-unstake) Earn strategies + real APYs, per asset.
  2. Bonded/timed strategies (shown for context — the bot won't use these).
  3. Your current Earn allocations.
  4. A funding+earn "stacked yield" preview for the coins in your config, using
     live Hyperliquid funding so you can eyeball selection before going live.

Run:  python3 kraken_earn_probe.py --config bot/config.yaml
This confirms the response shapes (asset codes, APR fields, lock types) that
exchanges.py parses, so you can flip earn_enabled: true with confidence.
"""
from __future__ import annotations

import argparse
import sys

import yaml

HRS_YR = 24 * 365


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="bot/config.yaml")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    kr_cfg = cfg.get("kraken", {}) or {}
    key, sec = kr_cfg.get("api_key", ""), kr_cfg.get("api_secret", "")
    if not (key and sec):
        print("ERROR: kraken.api_key / api_secret missing in", args.config)
        return 2

    import ccxt
    ex = ccxt.kraken({"apiKey": key, "secret": sec, "enableRateLimit": True})
    ex.load_markets()

    def coin_of(asset: str) -> str:
        try:
            return ex.safe_currency_code(asset)
        except Exception:  # noqa: BLE001
            return asset

    # --- 1+2. Strategies ---
    print("=" * 70)
    print("KRAKEN EARN STRATEGIES")
    print("=" * 70)
    try:
        resp = ex.privatePostEarnStrategies({"limit": 1000})
    except Exception as e:  # noqa: BLE001
        print("Earn/Strategies failed:", e)
        return 1
    items = ((resp or {}).get("result") or {}).get("items", []) or []
    flex, other = [], []
    for it in items:
        lock = ((it.get("lock_type") or {}).get("type") or "?").lower()
        apr_est = it.get("apr_estimate") or {}
        try:
            lo = float(apr_est.get("low", 0) or 0)
            hi = float(apr_est.get("high", lo) or lo)
        except (TypeError, ValueError):
            lo = hi = 0.0
        row = {
            "coin": coin_of(it.get("asset", "")),
            "asset": it.get("asset", ""),
            "lock": lock,
            "apr": (lo + hi) / 2.0,
            "lo": lo, "hi": hi,
            "min": it.get("user_min_allocation", ""),
            "id": it.get("id", ""),
            "can_alloc": it.get("can_allocate", True),
        }
        (flex if lock == "instant" else other).append(row)

    flex.sort(key=lambda r: -r["apr"])
    print(f"\n--- FLEX / instant-unstake ({len(flex)}) — these are what the bot uses ---")
    print(f"{'coin':<8}{'asset':<10}{'APR%':>8}{'(lo-hi)':>14}{'min':>12}  can_alloc")
    for r in flex:
        rng = f"{r['lo']:.1f}-{r['hi']:.1f}"
        print(f"{r['coin']:<8}{r['asset']:<10}{r['apr']:>8.2f}"
              f"{rng:>14}{str(r['min']):>12}  {r['can_alloc']}")

    print(f"\n--- bonded / timed ({len(other)}) — shown for context; bot SKIPS these ---")
    for r in sorted(other, key=lambda r: -r["apr"])[:25]:
        print(f"{r['coin']:<8}{r['asset']:<10}{r['apr']:>8.2f}  lock={r['lock']}")

    flex_apy = {r["coin"]: r["apr"] / 100.0 for r in flex}

    # --- 3. Current allocations ---
    print("\n" + "=" * 70)
    print("CURRENT EARN ALLOCATIONS")
    print("=" * 70)
    try:
        aresp = ex.privatePostEarnAllocations({"hide_zero_allocations": True})
        aitems = ((aresp or {}).get("result") or {}).get("items", []) or []
        if not aitems:
            print("(none)")
        for it in aitems:
            asset = it.get("native_asset") or it.get("asset")
            tot = (it.get("amount_allocated") or {}).get("total") or {}
            print(f"  {coin_of(asset):<8} allocated={tot.get('native','?')} "
                  f"(~{tot.get('converted','?')} conv)  strat={it.get('strategy_id','?')}")
    except Exception as e:  # noqa: BLE001
        print("Earn/Allocations failed:", e)

    # --- 4. Stacked-yield preview for config coins ---
    coins = [a["coin"] for a in cfg.get("assets", [])]
    if coins:
        print("\n" + "=" * 70)
        print("STACKED YIELD PREVIEW (live HL funding + flex earn) for config coins")
        print("=" * 70)
        try:
            from hyperliquid.info import Info
            info = Info(cfg.get("hyperliquid", {}).get("base_url", "https://api.hyperliquid.xyz"),
                        skip_ws=True)
            meta, ctxs = info.meta_and_asset_ctxs()
            fund = {a["name"]: float(c.get("funding", 0.0))
                    for a, c in zip(meta["universe"], ctxs)}
        except Exception as e:  # noqa: BLE001
            print("HL funding fetch failed:", e)
            fund = {}
        print(f"{'coin':<8}{'HLfund_ann%':>12}{'flex_earn%':>12}{'STACK%':>9}")
        rows = []
        for c in coins:
            fa = fund.get(c, 0.0) * HRS_YR * 100
            fe = flex_apy.get(c, 0.0) * 100
            rows.append((fa + fe, c, fa, fe))
        for stack, c, fa, fe in sorted(rows, reverse=True):
            tag = "" if c in flex_apy else "  (no flex strategy)"
            print(f"{c:<8}{fa:>12.1f}{fe:>12.2f}{stack:>9.1f}{tag}")

    print("\nDone. If the FLEX list + APYs look right, set earn_enabled: true in the config.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
