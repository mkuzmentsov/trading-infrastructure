import gzip,json,glob,collections,statistics as st,sys
COINS=['btc','eth','sol','xrp','doge','bnb']
LIM=200
GATES=[1.0,3.0,5.0,8.0]
agg=collections.defaultdict(lambda:[0,0,0.0,0.0])
for COIN in COINS:
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
                if tl is not None and 3<=tl<=12:          # LATE lane only
                    snaps[d['ws']].append((tl,d.get('ua'),d.get('uas'),d.get('da'),d.get('das')))
    for ws,sn in snaps.items():
        if ws not in res: continue
        T=ws+300
        sw=[S[x] for x in range(ws-62,ws-2) if x in S]
        if len(sw)<40: continue
        strike=st.mean(sw)
        seen=set()
        for tl,ua,uas,da,das in sorted(sn,reverse=True):
            cut=int(T-tl)
            kn=[S[x] for x in range(T-62,min(cut,T-2)) if x in S]
            if len(kn)<25: continue
            ntot=len(range(T-62,T-2))
            est=(sum(kn)+(ntot-len(kn))*kn[-1])/ntot
            m=(est-strike)/strike*1e4
            side='UP' if m>0 else 'DOWN'
            ask,sz=(ua,uas) if side=='UP' else (da,das)
            if not ask or (sz or 0)<5: continue
            ab=('<=0.55' if ask<=0.55 else '0.55-0.75' if ask<=0.75 else
                '0.75-0.90' if ask<=0.90 else '0.90-0.98' if ask<=0.98 else '>0.98')
            won=(res[ws]==side)
            for G in GATES:
                if abs(m)<G: continue
                k=(G,ab)
                if k in seen: continue
                seen.add(k)
                g=agg[k]; g[0]+=1; g[1]+=won; g[2]+=(1.0 if won else 0.0)-ask; g[3]+=ask
print('LATE LANE ONLY (tl 3-12s) — does a STRICTER margin gate rescue the cheap bands?')
print('If cheap-band losses are PROXY NOISE, a gate far above the 0.46bps error should flip them positive.\n')
print('  gate     ask band      n     win%   breakeven%    ROI%')
for G in GATES:
    for ab in ('<=0.55','0.55-0.75','0.75-0.90','0.90-0.98','>0.98'):
        n,w,p,c=agg[(G,ab)]
        if not n: continue
        print('  >=%.0fbps  %-11s %5d  %6.1f%%   %6.1f%%    %+7.2f%%'%(G,ab,n,100*w/n,100*c/n,100*p/c if c else 0))
    print()
