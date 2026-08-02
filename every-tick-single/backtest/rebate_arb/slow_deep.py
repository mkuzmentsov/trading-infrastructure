"""Artifact hunt on the positive dual-ask result. Every check that killed a
prior 'positive' is re-applied here: hidden-queue extremes, neutralise
slippage, entry-time, decomposition, and the 5m cross-check (did §4g's 'worst
config' verdict come only from RIDING the stuck leg?)."""
import math
import fast, msell

FEE_RATE, REBATE_SHARE = 0.07, 0.20
def rebate(p, sh): return REBATE_SHARE*FEE_RATE*p*(1-p)*sh
def taker_fee(p, sh): return FEE_RATE*p*(1-p)*sh


def run(coins, aU, aD, size=100.0, tl_hi=3600.0, delay=1.0, hidden=0.0,
        slip=0.0):
    out = []
    for coin in coins:
        for ws, m in fast.load(coin).items():
            fu, tu = msell._ask_leg(m, "UP", aU, size, tl_hi, 0.0, hidden)
            fd, td = msell._ask_leg(m, "DOWN", aD, size, tl_hi, 0.0, hidden)
            if fu <= 0 and fd <= 0:
                continue
            paired = min(fu, fd)
            reb = rebate(aU, fu) + rebate(aD, fd)
            lock = paired * (aU + aD - 1.0)
            neut = 0.0
            if fu > fd:
                stuck, resid, spx, rtl = "DOWN", fu - fd, aU, tu
            else:
                stuck, resid, spx, rtl = "UP", fd - fu, aD, td
            if resid > 0.5 and rtl is not None:
                b = msell._bid_at(m, rtl - delay, stuck)
                b = max((b if b is not None else 0.0) - slip, 0.0)
                neut = resid * (spx + b - 1.0) - taker_fee(b, resid)
            out.append(dict(ws=ws, coin=coin, fu=fu, fd=fd, paired=paired,
                            resid=resid, lock=lock, reb=reb, neut=neut,
                            net=lock + reb + neut))
    return out


def rep(rows, label):
    if not rows:
        return f"{label:52s} NO FILLS"
    n = len(rows)
    net = sum(r["net"] for r in rows)
    lock = sum(r["lock"] for r in rows); reb = sum(r["reb"] for r in rows)
    neut = sum(r["neut"] for r in rows)
    both = sum(1 for r in rows if r["paired"] > 0.5)
    legged = [r for r in rows if r["resid"] > 0.5]
    psh = sum(r["paired"] for r in rows) / n
    vals = [r["net"] for r in rows]; mu = net / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1)) if n > 1 else 0
    t = mu / (sd / math.sqrt(n)) if sd else 0
    worst = min((r["net"] for r in rows), default=0)
    return (f"{label:52s} bars={n:4d} both={100*both/n:3.0f}% pair_sh/bar={psh:5.1f} "
            f"lock=${lock:+8.2f} reb=${reb:+6.2f} neut=${neut:+8.2f} "
            f"NET=${net:+9.2f} ${mu:+.4f}/bar t={t:+6.2f} worst_bar=${worst:+.2f}")


if __name__ == "__main__":
    H = ["btc-mrec1h"]
    print("== hidden-queue extremes, 0.55/0.55 neutral@1s ==")
    for hid in (0, 50, 200, 500, 1000, 2000):
        print(rep(run(H, 0.55, 0.55, hidden=hid), f"1h 0.55 hid={hid}"))

    print("\n== neutralise slippage stress (dump price haircut), hid=200 ==")
    for slip in (0.0, 0.01, 0.02, 0.05):
        print(rep(run(H, 0.55, 0.55, hidden=200, slip=slip), f"1h 0.55 hid=200 slip={slip}"))

    print("\n== margin sweep, hid=200, neutral@1s ==")
    for a in (0.52, 0.55, 0.58, 0.60, 0.65, 0.70):
        print(rep(run(H, a, a, hidden=200), f"1h {a}/{a} hid=200"))

    print("\n== entry time (rest later into the bar), 0.55 hid=200 ==")
    for tl_hi in (3600, 2700, 1800, 900):
        print(rep(run(H, 0.55, 0.55, tl_hi=float(tl_hi), hidden=200), f"1h 0.55 from tl={tl_hi}"))

    print("\n== reaction delay sensitivity, 0.55 hid=200 ==")
    for d in (0.5, 1.0, 3.0, 10.0, 30.0):
        print(rep(run(H, 0.55, 0.55, hidden=200, delay=d), f"1h 0.55 delay={d}s"))

    print("\n== THE 5m CROSS-CHECK: same config on the 5m btc cache ==")
    for hid in (0, 50, 200):
        print(rep(run(["btc"], 0.55, 0.55, tl_hi=300.0, hidden=hid), f"5m btc 0.55 hid={hid}"))
        print(rep(run(["btc"], 0.52, 0.52, tl_hi=300.0, hidden=hid), f"5m btc 0.52 hid={hid}"))
    print("\n== 5m ALL SIX coins, 0.55 hid=200 ==")
    print(rep(run(["btc", "eth", "sol", "xrp", "bnb", "doge"], 0.55, 0.55,
                  tl_hi=300.0, hidden=200), "5m x6 0.55 hid=200"))
