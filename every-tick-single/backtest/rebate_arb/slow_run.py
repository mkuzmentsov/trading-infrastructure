"""Remaining slow-bar configs: (a) mint+dual-ask farmer with a DELAY-based
neutraliser (dump the stuck complement ~1s after the single fill -- msell.py
only had an absolute-time rescue), (b) seqmaker user-v2 rescue sweep on the
hourly clock."""
import math
import fast, msell, seqmaker

FEE_RATE, REBATE_SHARE = 0.07, 0.20
def rebate(p, sh): return REBATE_SHARE*FEE_RATE*p*(1-p)*sh
def taker_fee(p, sh): return FEE_RATE*p*(1-p)*sh


def dual_ask_delay(coins, aU, aD, size=100.0, tl_hi=3600.0, delay=1.0, hidden=0.0):
    out = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            fu, tu = msell._ask_leg(m, "UP", aU, size, tl_hi, 0.0, hidden)
            fd, td = msell._ask_leg(m, "DOWN", aD, size, tl_hi, 0.0, hidden)
            if fu <= 0 and fd <= 0:
                continue
            paired = min(fu, fd)
            reb = rebate(aU, fu) + rebate(aD, fd)
            pnl = paired * (aU + aD - 1.0)
            if fu > fd:
                stuck, resid, spx, rtl = "DOWN", fu - fd, aU, tu
            else:
                stuck, resid, spx, rtl = "UP", fd - fu, aD, td
            if resid > 0.5 and rtl is not None:
                b = msell._bid_at(m, rtl - delay, stuck)
                b = b if b is not None else 0.0
                pnl += resid * (spx + b - 1.0) - taker_fee(b, resid)
            out.append(dict(net=pnl + reb, rebate=reb, paired=paired, resid=resid))
    return out


def rep(rows, label):
    if not rows:
        return f"{label:46s} NO FILLS"
    n = len(rows); net = sum(r["net"] for r in rows)
    reb = sum(r["rebate"] for r in rows)
    both = sum(1 for r in rows if r["paired"] > 0.5)
    legged = sum(1 for r in rows if r["resid"] > 0.5)
    vals = [r["net"] for r in rows]; mu = net / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1)) if n > 1 else 0
    t = mu / (sd / math.sqrt(n)) if sd else 0
    return (f"{label:46s} bars={n:4d} both={100*both/n:3.0f}% legged={100*legged/n:3.0f}% "
            f"reb=${reb:+7.2f} NET=${net:+9.2f} ${mu:+.4f}/bar t={t:+6.2f}")


if __name__ == "__main__":
    C = ["btc-mrec1h"]
    print("== MINT + DUAL-ASK on hourly (89% of taker flow is buys) ==")
    for a in (0.51, 0.52, 0.55):
        for hidden in (0, 50, 200):
            rows = dual_ask_delay(C, a, a, tl_hi=3600.0, delay=1.0, hidden=hidden)
            print(rep(rows, f"1h ask {a}/{a} hid={hidden} neutral@1s"))
        rows = msell.run(C, a, a, tl_hi=3600.0, tl_lo=0.0, hidden=50, rescue_tl=None)
        print(msell.report(rows, f"1h ask {a}/{a} hid=50 RIDE"))
        print()
    print("== SEQMAKER user-v2 on hourly: p1 bid, maker complement after fill, taker rescue ==")
    for wait in (60, 300, 900):
        rows = seqmaker.run(C, 0.48, margin=0.0, size=100.0, tl_hi=3600.0,
                            rescue_tl=60.0, hidden=50, wait_secs=wait)
        print(seqmaker.report(rows, f"1h v2 p1=0.48 rescue@fill+{wait}s hid=50"))
    for wait in (300,):
        rows = seqmaker.run(C, 0.45, margin=0.02, size=100.0, tl_hi=3600.0,
                            rescue_tl=60.0, hidden=50, wait_secs=wait)
        print(seqmaker.report(rows, f"1h v2 p1=0.45 margin=2c rescue@fill+{wait}s hid=50"))
