"""MINT + DUAL-ASK farmer: split $1 into UP+DOWN (fee-free mint), rest maker
ASKS on both tokens at aU + aD = 1 + margin.

Why this could differ from every failed bid-side config: taker flow on these
markets is ~96% BUYS (shorting UP is done by buying DOWN, so taker sells barely
exist). Resting bids farm 4% of the flow; resting asks farm the 96%. Both-side
completion locks margin + double rebate; a stuck side means we sold the token
buyers wanted (the likely winner) and hold its complement (the likely loser).
Same adverse-selection shape as before -- but 24x the flow, so the both-fill
rate is the open question the tape can answer.
"""
import math
import fast

FEE_RATE, REBATE_SHARE = 0.07, 0.20

def rebate(p, sh): return REBATE_SHARE*FEE_RATE*p*(1-p)*sh
def taker_fee(p, sh): return FEE_RATE*p*(1-p)*sh

def _ask_leg(mkt, side, price, size, tl_hi, tl_lo, hidden):
    """Resting ASK filled by taker BUY prints at >= price. FIFO vs visible ask
    queue at join + hidden."""
    tok = "U" if side=="UP" else "D"
    ai, si = (5,6) if side=="UP" else (7,8)
    q=None
    for s in mkt["snaps"]:
        if s[0] > tl_hi: continue
        a, asz = s[ai], s[si]
        q = (asz if (a is not None and abs(a-price)<1e-9) else 0.0) + hidden
        break
    if q is None: return 0.0, None
    filled, first = 0.0, None
    for tl,t,px,sz,tside in mkt["sells"]:
        if tside!="BUY" or tl>tl_hi: continue
        if tl<=tl_lo or filled>=size: break
        if t!=tok or px < price-1e-9: continue
        if q>0:
            u=min(q,sz); q-=u; sz-=u
        if sz>0:
            filled+=min(sz,size-filled)
            if first is None: first=tl
    return filled, first

def _bid_at(mkt, tl_target, side):
    bi = 1 if side=="UP" else 3
    best=None
    for s in mkt["snaps"]:
        if s[0]>tl_target: best=s; continue
        return s[bi]
    return best[bi] if best else None

def run(coins, aU, aD, size=100.0, tl_hi=1200.0, tl_lo=0.0, hidden=0.0,
        rescue_tl=None):
    """Mint `size` sets, ask aU/aD. rescue_tl: taker-dump the unsold side into
    its bid at that tl; None = hold to resolution."""
    out=[]
    for coin in coins:
        for ws,m in fast.load(coin).items():
            fu,tu=_ask_leg(m,"UP",aU,size,tl_hi,tl_lo,hidden)
            fd,td=_ask_leg(m,"DOWN",aD,size,tl_hi,tl_lo,hidden)
            if fu<=0 and fd<=0: continue
            paired=min(fu,fd)
            reb=rebate(aU,fu)+rebate(aD,fd)
            pnl=paired*(aU+aD-1.0)
            if fu>fd: sold_side, stuck_side, resid, spx = "UP","DOWN",fu-fd,aU
            else:     sold_side, stuck_side, resid, spx = "DOWN","UP",fd-fu,aD
            if resid>0.5:
                # sold `resid` of one side at spx; still hold `resid` of stuck
                if rescue_tl is not None:
                    b=_bid_at(m,rescue_tl,stuck_side)
                    b=b if b is not None else 0.0
                    pnl += resid*(spx + b - 1.0) - taker_fee(b,resid)
                else:
                    won = (m["win"]==stuck_side)
                    pnl += resid*(spx + (1.0 if won else 0.0) - 1.0)
            out.append(dict(coin=coin,ws=ws,fu=fu,fd=fd,paired=paired,
                            resid=resid,pnl=pnl,rebate=reb,net=pnl+reb))
    return out

def report(rows,label):
    if not rows: return f"{label:44s} NO FILLS"
    n=len(rows); net=sum(r["net"] for r in rows); reb=sum(r["rebate"] for r in rows)
    both=sum(1 for r in rows if r["paired"]>0.5)
    legged=sum(1 for r in rows if r["resid"]>0.5)
    vals=[r["net"] for r in rows]; mu=net/n
    sd=math.sqrt(sum((x-mu)**2 for x in vals)/(n-1)) if n>1 else 0
    t=mu/(sd/math.sqrt(n)) if sd else 0
    return (f"{label:44s} bars={n:5d} both={100*both/n:3.0f}% legged={100*legged/n:3.0f}% "
            f"reb=${reb:+8.2f} NET=${net:+10.2f} ${mu:+.4f}/bar t={t:+6.2f}")
