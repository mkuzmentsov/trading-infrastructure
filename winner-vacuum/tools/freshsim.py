import gzip,json,glob,collections,statistics as st,sys
COIN=sys.argv[1] if len(sys.argv)>1 else 'btc'
LIM=int(sys.argv[2]) if len(sys.argv)>2 else 200
files=sorted(glob.glob(f'data/mrec/{COIN}/*.jsonl.gz'))[-LIM:]
S={}; snaps=collections.defaultdict(list); res={}
for f in files:
    with gzip.open(f,'rt') as fh:
        for l in fh:
            if '"SNAP"' not in l and '"RES"' not in l: continue
            try: d=json.loads(l)
            except: continue
            if d.get('ev')=='RES': res[d['ws']]=d['win']; continue
            if d.get('spot'): S[int(d['t'])]=d['spot']
            if d.get('role')!='cur': continue
            tl=d.get('tl')
            if tl is not None and 3<=tl<=30:
                snaps[d['ws']].append((tl,d.get('ua'),d.get('uas'),d.get('da'),d.get('das')))
def wmean(a,b,need):
    v=[S[x] for x in range(a,b) if x in S]
    return st.mean(v) if len(v)>=need else None
def est_at(T,cut):
    """TWAP-60 estimate using ticks known up to wall-clock `cut` (carry-forward)."""
    kn=[S[x] for x in range(T-62,min(cut,T-2)) if x in S]
    if len(kn)<25: return None
    ntot=len([1 for x in range(T-62,T-2)])
    return (sum(kn)+(ntot-len(kn))*kn[-1])/ntot
def run(delay,gate):
    n=w=0; cost=pay=0.0
    for ws,sn in snaps.items():
        if ws not in res: continue
        T=ws+300
        strike=wmean(ws-62,ws-2,40)
        if strike is None: continue
        fired=False
        for tl,ua,uas,da,das in sorted(sn,reverse=True):     # scan tl 30 -> 3
            if fired: break
            cut=int(T-tl-delay)                              # info horizon at this instant
            e=est_at(T,cut)
            if e is None: continue
            m=(e-strike)/strike*1e4
            if abs(m)<gate: continue
            side='UP' if m>0 else 'DOWN'
            ask,sz=(ua,uas) if side=='UP' else (da,das)
            if not ask or ask>0.99 or (sz or 0)<5: continue
            n+=1; cost+=ask; fired=True
            if res[ws]==side: w+=1; pay+=1.0
    return n,(100*w/n if n else 0),((pay-cost)/cost*100 if cost else 0),(pay-cost)
print(f'=== {COIN}: value of FRESHNESS (same price source, only the info delay differs) ===')
print('  bars=%d'%len(snaps))
print('  %-26s %8s %8s %9s %9s'%('variant','trades','win%','ROI%','net$/1sh'))
for gate in (1.0,2.0):
    for delay,lbl in ((0.0,'FRESH (binance ~0.14s)'),(2.2,'RELAY-DELAYED (2.2s)')):
        n,wp,roi,net=run(delay,gate)
        print('  gate>=%.0fbps %-14s %8d %7.1f%% %8.2f%% %9.2f'%(gate,lbl,n,wp,roi,net))
