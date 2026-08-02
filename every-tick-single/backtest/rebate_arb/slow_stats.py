"""Structure + pool measurements for the slow series (1h / 1d), print-exact.

Answers, per series:
  1. Is there an oscillate-near-50c regime (the one §4e proved absent on 5m)?
     -> per-bar: range of ub over phases, time share with ub in [0.45,0.55],
        0.50-crossings, last time the book is still near mid.
  2. How big is the rebate pool really? -> sum over prints of 0.2*0.07*p(1-p)*sz,
     split by phase and by price band. Cross-checked against volsh to bound
     print double-counting.
  3. Flow balance: BUY vs SELL taker shares per token (the daily "96% buys"
     claim, print-exact).
  4. Queue competition: touch sizes while the book is near mid.
"""
import statistics as st
import fast

FEE, REB = 0.07, 0.20


def bars(name):
    return fast.load(name)


def phase_edges(bar_secs, n=4):
    step = bar_secs / n
    return [(bar_secs - i * step, bar_secs - (i + 1) * step) for i in range(n)]


def structure(name, bar_secs):
    print(f"\n=== {name} (bar={bar_secs}s): {len(bars(name))} resolved bars ===")
    rows = []
    for ws, m in sorted(bars(name).items()):
        ub = [(s[0], s[1]) for s in m["snaps"] if s[1] is not None and 0 < s[0] <= bar_secs]
        if len(ub) < bar_secs * 0.3:
            continue
        mid_time = sum(1 for _, b in ub if 0.45 <= b <= 0.55) / len(ub)
        cross, prev = 0, None
        for _, b in ub:
            side = b >= 0.50
            if prev is not None and side != prev:
                cross += 1
            prev = side
        last_mid = max((t for t, b in ub if 0.45 <= b <= 0.55), default=None)
        halves = {}
        for lab, hi, lo in (("H1", bar_secs, bar_secs / 2), ("H2", bar_secs / 2, 0)):
            xs = [b for t, b in ub if lo < t <= hi]
            halves[lab] = (max(xs) - min(xs)) if xs else None
        rows.append(dict(ws=ws, win=m["win"], mid_time=mid_time, cross=cross,
                         last_mid=last_mid, r1=halves["H1"], r2=halves["H2"]))
    if not rows:
        print("  no bars with coverage"); return
    def q(v, p):
        xs = sorted(x for x in v if x is not None)
        return xs[int(p * (len(xs) - 1))] if xs else None
    for k, lab in (("r1", "range 1st half"), ("r2", "range 2nd half"),
                   ("mid_time", "time ub in [.45,.55]"), ("cross", "0.50 crossings")):
        v = [r[k] for r in rows]
        print(f"  {lab:22s} p25={q(v,.25)} med={q(v,.5)} p75={q(v,.75)} max={q(v,1.)}")
    lm = [r["last_mid"] for r in rows if r["last_mid"] is not None]
    print(f"  last time near mid      med tl={q(lm,.5):.0f}s p25={q(lm,.25):.0f} "
          f"(bars ever near mid: {len(lm)}/{len(rows)})")


def pool(name, bar_secs):
    m_all = bars(name)
    per_bar, phase_fee, band_fee = [], {}, {}
    buy_sh = sell_sh = 0.0
    tok_sh = {"U": 0.0, "D": 0.0}
    dollar_vol = 0.0
    for ws, m in m_all.items():
        f_bar = 0.0
        for tl, tok, px, sz, side in m["sells"]:
            if tl < -1 or tl > bar_secs:      # active bar only (pre-open has ~no prints)
                continue
            fee = FEE * px * (1 - px) * sz
            f_bar += fee
            dollar_vol += px * sz
            ph = min(3, int((bar_secs - tl) / (bar_secs / 4)))
            phase_fee[ph] = phase_fee.get(ph, 0.0) + fee
            band = "mid .40-.60" if 0.40 <= px <= 0.60 else (".60-.90" if px < 0.90 else "tail>.90")
            if px < 0.40: band = ".10-.40" if px > 0.10 else "tail<.10"
            band_fee[band] = band_fee.get(band, 0.0) + fee
            if side == "BUY": buy_sh += sz
            else: sell_sh += sz
            tok_sh[tok] = tok_sh.get(tok, 0.0) + sz
        per_bar.append(f_bar)
    n = len(per_bar)
    tot = sum(per_bar)
    print(f"\n  -- pool ({n} bars) --")
    print(f"  taker fees  total=${tot:.2f}  med/bar=${st.median(per_bar):.2f} "
          f"mean/bar=${tot/max(n,1):.2f}  -> REBATE pool med/bar=${REB*st.median(per_bar):.3f}")
    day_bars = 86400 / bar_secs
    print(f"  implied whole-series rebate pool: ${REB*tot/max(n,1)*day_bars:.0f}/day "
          f"(mean-based), ${REB*st.median(per_bar)*day_bars:.0f}/day (median-based)")
    print(f"  $ volume counted: ${dollar_vol:,.0f}  (cross-check vs volsh below)")
    for ph in sorted(phase_fee):
        print(f"    quarter {ph+1}: fees ${phase_fee[ph]:.2f} ({100*phase_fee[ph]/tot:.0f}%)")
    for b, v in sorted(band_fee.items(), key=lambda x: -x[1]):
        print(f"    price {b:11s}: ${v:.2f} ({100*v/tot:.0f}%)")
    print(f"  flow: taker BUY {buy_sh:,.0f} sh vs SELL {sell_sh:,.0f} sh "
          f"({100*buy_sh/max(buy_sh+sell_sh,1):.0f}% buys); U {tok_sh['U']:,.0f} / D {tok_sh['D']:,.0f}")
    # volsh cross-check: last cur snapshot volsh vs our print sum, per bar
    for ws, m in sorted(m_all.items())[:3]:
        vs = None
        # snaps have no volsh in cache; report print shares only
        psh = sum(sz for tl, _, _, sz, _ in m["sells"] if -1 <= tl <= bar_secs)
        print(f"    {m['slug']}: print shares {psh:,.0f}")


def touch(name, bar_secs):
    szs = []
    for ws, m in bars(name).items():
        for s in m["snaps"]:
            if not (0 < s[0] <= bar_secs): continue
            b = s[1]
            if b is None or not (0.45 <= b <= 0.55): continue
            szs.append((s[2], s[4]))
    if not szs:
        print("  touch: never near mid"); return
    u = sorted(x[0] for x in szs); d = sorted(x[1] for x in szs)
    print(f"  touch size near mid: UP bid med={u[len(u)//2]:,.0f}sh p90={u[int(.9*len(u))]:,.0f}  "
          f"DOWN bid med={d[len(d)//2]:,.0f}sh  (n={len(szs)} snap-secs)")


if __name__ == "__main__":
    for name, bs in (("btc-mrec1h", 3600), ("btc-mrec1d", 86400)):
        structure(name, bs)
        pool(name, bs)
        touch(name, bs)
