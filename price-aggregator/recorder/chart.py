#!/usr/bin/env python3
"""Two-venue price comparison chart: our Aggregate (Binance) vs Polymarket RTDS
Chainlink. Aggregate is basis-adjusted (minus the persistent ~$53 USDT/USD basis)
so the two overlay and the ~2.5s lead is visible. Picks the most volatile window."""
import json, sys, statistics
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PATH = sys.argv[1] if len(sys.argv) > 1 else "data/delay.jsonl"
OUT  = sys.argv[2] if len(sys.argv) > 2 else "data/venue_compare.png"

BLUE, ORANGE = "#2a78d6", "#eb6834"          # validated categorical pair
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e6e3"

rows = []
for line in open(PATH):
    try: r = json.loads(line)
    except Exception: continue
    if r.get("ev") == "s" and r.get("agg") and r.get("cl"):
        rows.append(r)
rows.sort(key=lambda r: r["t"])
basis = statistics.median(r["agg"] - r["cl"] for r in rows)   # ~$53

# most volatile ~3-min window (by Chainlink range)
W = 180.0
best = None
i = 0
for a in range(0, len(rows), 40):
    t0 = rows[a]["t"]
    seg = [r for r in rows[a:a+900] if r["t"] - t0 <= W]
    if len(seg) < 100: continue
    rng = max(r["cl"] for r in seg) - min(r["cl"] for r in seg)
    if best is None or rng > best[0]:
        best = (rng, seg)
seg = best[1]
t0 = seg[0]["t"]
xs = [r["t"] - t0 for r in seg]
cl = [r["cl"] for r in seg]
agg = [r["agg"] - basis for r in seg]        # basis-adjusted overlay

# zoom: 40s around the steepest cl slope inside the window
mid = max(range(5, len(seg)-5), key=lambda k: abs(seg[k+5]["cl"] - seg[k-5]["cl"]))
zt = seg[mid]["t"] - t0
zlo, zhi = zt - 20, zt + 20

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7.2), gridspec_kw={"height_ratios": [2, 1]})
fig.patch.set_facecolor(SURFACE)
for ax in (ax1, ax2):
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, lw=0.8, zorder=0)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=INK2, labelsize=9)

ax1.plot(xs, agg, color=BLUE, lw=2, zorder=3, label="Aggregate (Binance), basis-adj")
ax1.plot(xs, cl, color=ORANGE, lw=2, zorder=2, label="Chainlink (Polymarket RTDS)")
ax1.axvspan(zlo, zhi, color="#000000", alpha=0.045, zorder=1)
ax1.set_title("BTC price: our Aggregate leads the Chainlink resolution feed by ~2.5s",
              color=INK, fontsize=13, fontweight="bold", loc="left", pad=12)
ax1.set_ylabel("USD  (Chainlink scale)", color=INK2, fontsize=9)
leg = ax1.legend(loc="best", frameon=False, fontsize=10)
for t in leg.get_texts(): t.set_color(INK)

zx = [x for x in xs if zlo <= x <= zhi]
za = [agg[k] for k, x in enumerate(xs) if zlo <= x <= zhi]
zc = [cl[k]  for k, x in enumerate(xs) if zlo <= x <= zhi]
ax2.plot(zx, za, color=BLUE, lw=2.2, zorder=3)
ax2.plot(zx, zc, color=ORANGE, lw=2.2, zorder=2)
ax2.set_title("Zoom on the fastest move — blue (real-time) turns before orange (lagged)",
              color=INK2, fontsize=10, loc="left", pad=8)
ax2.set_xlabel("seconds", color=INK2, fontsize=9)
ax2.set_ylabel("USD", color=INK2, fontsize=9)

fig.text(0.008, 0.008,
         f"{len(rows):,} samples · 8h · basis removed = ${basis:,.0f} (BTCUSDT vs BTC/USD)",
         color=INK2, fontsize=8)
fig.tight_layout(rect=[0, 0.02, 1, 1])
fig.savefig(OUT, dpi=150, facecolor=SURFACE)
print("wrote", OUT)
