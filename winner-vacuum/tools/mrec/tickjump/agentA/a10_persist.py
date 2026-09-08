import mm, lw2, lw4, pandas as pd
D={c:mm.load_coin(c) for c in mm.COINS}; NB=sum(len(set(D[c][0].ws)) for c in mm.COINS)
def go(lab,**kw):
    d=pd.concat([lw4.run(c,*D[c],**kw) for c in mm.COINS],ignore_index=True); lw2.score(d,lab,NB)
    b=d.groupby(['coin','ws']).win.max(); print(f'      losing bars {int((b==0).sum())}'); return d
print('PERSIST sensitivity (pre-registered value = 5s; the rest is a curve, not a fit):')
for p in (0,2,5,10,15,20): go(f'PERSIST {p}s',PERSIST=float(p))
print('\nplacebo: persistence measured on the OPPOSITE token bid (>=0.98 on the other side is impossible, so use its bid<=0.02 for >=5s) == same bars but the gate keyed on the underdog side')
