"""IMPLEMENTABLE-policy state machine for the dual-ask harvest -- fixes the
look-ahead in slow_deep.py, which dumped the EVENTUAL residual at first-fill
+1s (unknowable then; and any real rule that waits to allow pairing dumps
later, at a worse price, in trend bars).

Mechanics per bar: mint SIZE pairs at open, rest asks at `a` on both tokens.
Prints fill asks FIFO behind (visible-at-entry + hidden) queue. Policies for
the imbalance |fu-fd|:
  timer-X : when an imbalance appears, start X-second timer (reset if it pairs
            back to zero). On expiry: dump imbalance at stuck side's bid,
            cancel both asks, done for the bar. X=None -> never (imbalance
            rides to settlement = the old 'ride').
  stop-K  : dump + cancel the moment the stuck side's bid <= K.
Both dumps pay the taker fee. Fully-paired-within-policy bars lock
SIZE*(2a-1); leftover matched pairs redeem $1 (no exposure). Rebates on all
maker fills. Clock = 1Hz snapshots; prints applied between ticks.
"""
import math
import fast

FEE_RATE, REBATE_SHARE = 0.07, 0.20


def run(coins, a, size=100.0, tl_hi=None, hidden=0.0, timer=None, stop=None,
        slip=0.0):
    out = []
    for coin in coins:
        bar = 3600.0 if "1h" in coin else (86400.0 if "1d" in coin else 300.0)
        hi = tl_hi if tl_hi is not None else bar
        for ws, m in fast.load(coin).items():
            snaps = [s for s in m["snaps"] if s[0] <= hi]      # chronological
            if not snaps:
                continue
            # queue seeding at entry, per leg (same convention as msell)
            s0 = snaps[0]
            qU = (s0[6] if (s0[5] is not None and abs(s0[5] - a) < 1e-9) else 0.0) + hidden
            qD = (s0[8] if (s0[7] is not None and abs(s0[7] - a) < 1e-9) else 0.0) + hidden
            prints = [p for p in m["sells"] if p[0] <= hi and p[4] == "BUY"]
            pi = 0
            fu = fd = 0.0
            reb = pnl = 0.0
            deadline = None            # tl at which timer expires
            done = False
            dumped = 0.0
            for s in snaps:
                tl = s[0]
                # apply prints since previous tick
                while pi < len(prints) and prints[pi][0] >= tl:
                    ptl, tok, px, sz, _ = prints[pi]; pi += 1
                    if done or px < a - 1e-9:
                        continue
                    if tok == "U" and fu < size:
                        if qU > 0:
                            u = min(qU, sz); qU -= u; sz -= u
                        if sz > 0:
                            got = min(sz, size - fu); fu += got
                            reb += REBATE_SHARE * FEE_RATE * a * (1 - a) * got
                    elif tok == "D" and fd < size:
                        if qD > 0:
                            u = min(qD, sz); qD -= u; sz -= u
                        if sz > 0:
                            got = min(sz, size - fd); fd += got
                            reb += REBATE_SHARE * FEE_RATE * a * (1 - a) * got
                if done:
                    continue
                imb = fu - fd
                if abs(imb) < 0.5:
                    deadline = None
                    continue
                stuck = "D" if imb > 0 else "U"       # under-SOLD side we hold extra of
                sbid = s[3] if stuck == "D" else s[1]
                if timer is not None:
                    if deadline is None:
                        deadline = tl - timer
                    trig_t = tl <= deadline
                else:
                    trig_t = False
                trig_s = (stop is not None and sbid is not None and sbid <= stop)
                if trig_t or trig_s:
                    b = max((sbid if sbid is not None else 0.0) - slip, 0.0)
                    q = abs(imb)
                    pnl += q * (a + b - 1.0) - FEE_RATE * b * (1 - b) * q
                    dumped = q
                    done = True
            paired = min(fu, fd)
            pnl += paired * (2 * a - 1.0)
            if not done and abs(fu - fd) > 0.5:       # rode to settlement
                stuck = "D" if fu > fd else "U"
                sval = 1.0 if (stuck == "U") == (m["win"] == "UP") else 0.0
                pnl += abs(fu - fd) * (a + sval - 1.0)
            if fu + fd > 0.5:
                out.append(dict(ws=ws, coin=coin, fu=fu, fd=fd, paired=paired,
                                dumped=dumped, reb=reb, net=pnl + reb))
    return out


def rep(rows, label):
    if not rows:
        return f"{label:48s} NO FILLS"
    n = len(rows)
    net = sum(r["net"] for r in rows)
    reb = sum(r["reb"] for r in rows)
    both = sum(1 for r in rows if r["paired"] >= min(r["fu"], 99.5) and r["paired"] > 0.5)
    full = sum(1 for r in rows if r["paired"] > 99.5)
    dmp = sum(1 for r in rows if r["dumped"] > 0.5)
    vals = [r["net"] for r in rows]
    mu = net / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1)) if n > 1 else 0.0
    t = mu / (sd / math.sqrt(n)) if sd else 0.0
    worst = min(vals)
    return (f"{label:48s} bars={n:4d} fullpair={100*full/n:3.0f}% dumped={100*dmp/n:3.0f}% "
            f"reb=${reb:+7.2f} NET=${net:+9.2f} ${mu:+.4f}/bar t={t:+6.2f} worst=${worst:+.2f}")


if __name__ == "__main__":
    print("== 5m btc, hid=200 -- implementable exits ==")
    for a in (0.55, 0.65):
        for lab, kw in (("ride (never exit)", dict()),
                        ("timer 10s", dict(timer=10.0)),
                        ("timer 30s", dict(timer=30.0)),
                        ("timer 60s", dict(timer=60.0)),
                        ("timer 120s", dict(timer=120.0)),
                        ("stop 0.40", dict(stop=0.40)),
                        ("stop 0.30", dict(stop=0.30)),
                        ("stop 0.25", dict(stop=0.25)),
                        ("stop 0.15", dict(stop=0.15)),
                        ("timer60+stop0.30", dict(timer=60.0, stop=0.30)),
                        ("timer120+stop0.25", dict(timer=120.0, stop=0.25))):
            print(rep(run(["btc"], a, hidden=200, **kw), f"5m btc {a} {lab}"))
        print()
    print("== 1h btc, hid=200 ==")
    for a in (0.55, 0.65):
        for lab, kw in (("ride", dict()),
                        ("timer 60s", dict(timer=60.0)),
                        ("timer 300s", dict(timer=300.0)),
                        ("timer 900s", dict(timer=900.0)),
                        ("stop 0.30", dict(stop=0.30)),
                        ("stop 0.25", dict(stop=0.25)),
                        ("timer300+stop0.25", dict(timer=300.0, stop=0.25))):
            print(rep(run(["btc-mrec1h"], a, hidden=200, **kw), f"1h {a} {lab}"))
        print()
    print("== sensitivity on the best exits ==")
    for hid in (0, 500, 1000):
        print(rep(run(["btc"], 0.65, hidden=hid, stop=0.25), f"5m btc 0.65 stop0.25 hid={hid}"))
    for slip in (0.02, 0.05):
        print(rep(run(["btc"], 0.65, hidden=200, stop=0.25, slip=slip), f"5m btc 0.65 stop0.25 slip={slip}"))
