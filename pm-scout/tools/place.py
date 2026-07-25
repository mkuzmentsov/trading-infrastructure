#!/usr/bin/env python3
"""pm-scout place — execution for APPROVED actions only. Reuses the tail-bot
CLOB engine (every-tick-single/src/engine/clob.py) with creds from the same
overlay wallet.py reads. NOTHING executes without --confirm (dry prints intent).

Subcommands:
  bet     --token T --price P --shares N [--taker]    BUY (post-only GTC maker
          default; --taker = FAK, only for time-critical theses)
  close   --token T --price P --shares N [--taker]    SELL (GTC maker / FAK)
  redeem                                              claim all resolved positions
Every confirmed action appends to runs/ledger.jsonl (with --thesis "...").
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
LEDGER = os.path.join(HERE, "..", "runs", "ledger.jsonl")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "every-tick-single", "src"))

from wallet import creds  # noqa: E402


def _env_from_creds() -> None:
    c = creds()
    os.environ["POLYMARKET_PK"] = c.get("polymarketPrivateKey", "")
    os.environ["POLYMARKET_ADDRESS"] = c.get("polymarketAddress", "")
    os.environ["POLYMARKET_FUNDER"] = c.get("polymarketFunder", "")
    os.environ["POLYMARKET_SIGNATURE_TYPE"] = c.get("polymarketSignatureType", "0")
    os.environ["DRY_RUN"] = "false"


def _ledger(rec: dict) -> None:
    rec["t"] = round(time.time(), 2)
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["bet", "close", "redeem"])
    ap.add_argument("--token")
    ap.add_argument("--price", type=float)
    ap.add_argument("--shares", type=float)
    ap.add_argument("--taker", action="store_true")
    ap.add_argument("--thesis", default="")
    ap.add_argument("--confirm", action="store_true",
                    help="actually execute; without it, print intent only")
    a = ap.parse_args()

    if a.action in ("bet", "close") and not (a.token and a.price and a.shares):
        sys.exit("bet/close need --token --price --shares")

    intent = {k: v for k, v in vars(a).items() if v not in (None, False, "")}
    if not a.confirm:
        print("DRY (no --confirm): would execute:", json.dumps(intent))
        return

    _env_from_creds()
    from engine.clob import (build_clob_client, ensure_approvals,
                             place_limit_order, place_bet, place_limit_sell,
                             sign_sell_order, post_signed_sell_fak)
    clob = build_clob_client()
    ensure_approvals(clob)

    if a.action == "bet":
        if a.taker:
            oid, matched, px, qty = place_bet(clob, a.token, a.shares, a.price)
            res = {"order_id": oid, "matched": matched, "fill_px": px, "qty": qty}
        else:
            oid = place_limit_order(clob, a.token, "BUY", a.shares, a.price)
            res = {"order_id": oid, "post_only": True}
    elif a.action == "close":
        if a.taker:
            signed = sign_sell_order(clob, a.token, a.shares, a.price)
            oid, matched = post_signed_sell_fak(clob, signed)
            res = {"order_id": oid, "matched": matched}
        else:
            oid, matched = place_limit_sell(clob, a.token, a.shares, a.price)
            res = {"order_id": oid, "matched": matched}
    else:  # redeem
        from engine.redemptions import redeem_resolved_positions
        redeem_resolved_positions()
        res = {"redeem": "attempted (see log output)"}

    print("RESULT:", json.dumps(res))
    _ledger({"action": a.action, "token": a.token, "price": a.price,
             "shares": a.shares, "taker": a.taker, "thesis": a.thesis,
             "result": res})


if __name__ == "__main__":
    main()
