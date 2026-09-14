# Bar autopsy — `btc-updown-5m-1789241100` (2026-09-12 19:25–19:30 UTC)
**Built 2026-09-14 with `.claude/skills/pm-bar-dash`. Nothing deployed.**
Dashboard: <https://claude.ai/code/artifact/86895aac-dac5-4c4d-a5f4-93fc27c955e7>

**+$30.10 on one clip** — the largest fill in any autopsy, and **83% of btc's whole 09-12 day**
(9 fills, 0 losses, +$36.20). It is also the bar that **breaks the bid-drop veto's clean run.**

## 1. ⚠️⚠️ THE BID-DROP VETO WOULD HAVE DELETED THIS $30

`seen_ask 0.67` is **< `PM_TE_BIDDROP_MAX_ASK` 0.98**, so the rule is **in scope** — and the
favourite's (UP) own bid was in free fall:

```
fav UP bid   0.83 (T−25.7)  →  0.48 (at the fire)
dB6  = −0.350      dB10 = −0.400      dB20 = −0.410     →  BLOCK
```

All three windows block, decisively, and **UP won**. Scoreboard across the four bars autopsied:

| bar | seen_ask | dB6 | veto | outcome | veto right? |
|---|---|---|---|---|---|
| doge 1789403700 | 0.72 | −0.42 | BLOCK | −$3.65 | ✅ |
| btc 1789393200 | 0.79 | −0.14 | BLOCK | −$20.80 | ✅ |
| bnb 1789384200 | 0.99 | +0.13 | allow (out of scope) | +$9.06 | ✅ |
| **btc 1789241100** | **0.67** | **−0.35** | **BLOCK** | **+$30.10** | ❌ |

**3-for-4 — and the one it gets wrong is larger than the two it gets right combined.** On these
four bars the veto is **net −$5.65** (saves $24.45, forfeits $30.10).

This is not a refutation; it is **exactly the risk `strat-losstail-veto-20260910` §9 named in
advance**: *"We are deleting a fat-tailed class. 34 winning fills worth +$219 over 10 days go with
it. The net is a difference of two fat tails and is bootstrap-insignificant. **Judge the live
result on loss-bars/day, never on PnL.**"* Four bars is not a sample, and PnL is the metric that
doc told us not to use. But it is a concrete instance of the forfeited class, and it should stop
anyone (me included) reading "2-for-2" as momentum toward shipping.

⚠️ **Correction to my own framing.** In the previous two write-ups I said the bars "were selected
because they lost". That is wrong about provenance — **all four bars were supplied by the user**, I
selected none of them. The real defect was narrower and still real: the freshness lever was
*derived* on two bars that both happened to be losses and *tested* on none. Fixed in
[[naming-a-bias-is-not-controlling-for-it]].

## 2. The bar

| | |
|---|---|
| strike / final (`PF_TE_VERIFY`, err 0.0 bps) | 77139.1113 → 77141.1532 |
| margin | **+0.2647 bps** → **UP** |
| our fill | UP, displayed ask **0.67**, filled **47.78 sh @ 0.3700**, $17.68 |
| result | **+$30.10** ledger / **+$29.53** net of fee, ROI **+170%** |
| est at fire | **+0.919** vs `eff_thresh` **0.700** (tl 19.7) — the most comfortable of the four |

⚠️ **No Binance series on this bar.** `brec` only started 2026-09-13 17:40 UTC; this is 09-12, so
the tail-freshness question cannot even be asked here. That constraint is now the main thing
standing between the open questions and a real measurement.

## 3. The canonical stale-ask windfall

```
T−20.12    UP  0.91 / 0.92   × 1,920 shares      ← deep, solid
T−20.01    UP  0.47 / 0.91                       ← 110 ms later
T−19.91    UP  0.47 / 0.50
T−19.69    FIRE: limit 0.68, $17.68 → 47.78 sh @ 0.3700   (44.8¢ improvement)
```

Requested 26 shares; the dollar-denominated FAK took **47.78**. This is the shape memory already
records from 08-25 (*displayed 0.99, filled 41.7 sh @ $0.19 → +$33.76 = 34% of era profit*).

⭐ **And nothing observable at the fire separates it from the btc T13:40 bar that cost $20.80.**
Both: solid displayed ask, book collapses in ~110 ms during the round trip, dollar-FAK sweeps the
vacuum, `PF_TE_TOXIC_BRAKE` trips on the improvement. Same instrument, same signature, −$20.80 vs
+$30.10. On T13:40 the collapse was information (BTC had genuinely rallied, and Binance showed it);
here it was a liquidity vacuum and the price barely moved. **The bid direction, which separated the
first three bars, fails here** — it points down on both the $20.80 loss and this $30.10 win.

## 4. ⭐ First clearly pro-§37-delay bar

`PF_TE_WHALE_DELAY` blocked a fire at **T−29.9, ask 0.89, est +1.215**. Waiting for tl≤20 put the
same **$17.68** budget into a collapsed book: **47.78 shares instead of ~20**. Same side, same
conviction, **+$30.10 instead of roughly +$2**.

The delay gate has now been visibly implicated three ways across four bars — it cost the doge bar
~$3.74, it dropped the btc T13:40 fire into the collapse, and it earned ~$28 here. At ~30:1 payoff
that is exactly the noise the §37 note predicts; **none of these bars is evidence about the gate**,
and they are logged only so nobody re-derives one of them as a finding.

## 5. What actually moved

Chainlink drifted *down* through the window (dev −0.02 → −3.25 bps) while the 60-second average
stayed positive at **+0.265** — the early part of the window carried it. The estimate was stable and
correct the whole time (+1.22 → +0.92 at the fire → +0.265 at the close, never crossing zero). This
bar was won on the estimate, and the size was won on the sweep.

## 6. Reproduce

```bash
cd <repo root> && source ./.dev-env-source
python3 .claude/skills/pm-bar-dash/build_dash.py btc btc-updown-5m-1789241100 --outdir <scratch>
python3 .claude/skills/pm-bar-dash/assemble.py <scratch>/dash.json <scratch>/bar.html
```
⚠️ Needed a skill fix: `pod_entries` only grepped the live event log, so any bar older than today
returned zero entries. It now reads the rotated `logs-training-events.jsonl.<date>.gz` too.
