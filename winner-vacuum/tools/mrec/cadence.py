"""What if we clipped every N seconds, side-agnostic (each clip takes whatever the
estimator says NOW)?  Relative A/B: every arm shares one fill model, per the mrec
README's rule that only relative comparisons survive a replay."""
import sys; sys.path.insert(0, 'harness')
import pandas as pd, numpy as np, hx

CLIP_USD = 24.0                       # the live first-clip size
FEE = 0.07
P = pd.read_parquet('data/panel.parquet',
                    columns=['coin','ws','tlk','est_live','ua','uas','da','das','win'])
P['day'] = pd.to_datetime(P.ws, unit='s', utc=True).dt.strftime('%m-%d')

def fill_rate(a):
    r = np.full(len(a), np.nan)
    for lo, hi, f, _ in hx.BAND_FILL:
        r = np.where((a >= lo) & (a < hi), f, r)
    return r

def run(grid, label, cap=0.99, min_ask=0.55):
    g = P[P.tlk.isin(grid)].dropna(subset=['est_live']).copy()
    g['gate'] = 0.5 + 0.035 * np.maximum(0, g.tlk - 14)
    g = g[g.est_live.abs() >= g.gate]                       # decisive only
    g['side'] = np.where(g.est_live > 0, 'U', 'D')
    g['ask']  = np.where(g.side == 'U', g.ua, g.da)
    g['asz']  = np.where(g.side == 'U', g.uas, g.das)
    g = g.dropna(subset=['ask'])
    g = g[(g.ask >= min_ask) & (g.ask <= cap)]              # the live band
    g['pfill'] = fill_rate(g.ask.values)
    # dollar-denominated: $CLIP buys CLIP/ask shares, capped by displayed depth
    g['sh']   = np.minimum(CLIP_USD / g.ask, g.asz.fillna(0))
    g['cost'] = g.sh * g.ask
    g['wonit'] = (g.side == np.where(g.win == 'UP', 'U', 'D'))
    g['gross'] = np.where(g.wonit, g.sh * (1 - g.ask), -g.cost)
    g['fee']   = g.sh * FEE * g.ask * (1 - g.ask)
    g['net']   = (g.gross - g.fee) * g.pfill                # expected, at measured fill rates
    nbars = g.groupby(['coin','ws']).ngroups
    per_day = g.groupby('day').net.sum()
    return dict(label=label, slots=len(g), bars=nbars, clips_per_bar=len(g)/max(nbars,1),
                staked=(g.cost*g.pfill).sum(), net=g.net.sum(),
                roi=100*g.net.sum()/max((g.cost*g.pfill).sum(),1e-9),
                per_bar=g.net.sum()/max(nbars,1),
                days=' '.join('%s:%+.0f' % (d, v) for d, v in per_day.items()),
                worst=g.net.min(), best=g.net.max())

rows = [
    run([30,26,22,18,14,10,6],        'every 4s, tl 30->6'),
    run([20,16,12,8,4],               'every 4s, tl 20->4  (post vol-delay)'),
    run([30,22,14,6],                 'every 8s, tl 30->6  (~current cooldown)'),
    run([14],                         'single clip at tl 14'),
    run([20],                         'single clip at tl 20'),
    run([6],                          'single clip at tl 6'),
]
print('%-38s %6s %6s %7s %10s %9s %8s %9s' % ('policy','slots','bars','clips/bar','staked $','net $','ROI %','$/bar'))
for r in rows:
    print('%-38s %6d %6d %9.2f %10.0f %9.2f %8.2f %9.4f' %
          (r['label'], r['slots'], r['bars'], r['clips_per_bar'], r['staked'], r['net'], r['roi'], r['per_bar']))
print()
for r in rows[:3]:
    print('  %-38s per-day: %s   worst clip %+.2f' % (r['label'], r['days'], r['worst']))
