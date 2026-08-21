# vacmaker — offline support notes from the recorder datasets (2026-08-15 overnight session)

Companion to ../VACMAKER.md (the live program, parallel session). This
session ran the historical surface the live paper sweep is collecting
forward, on 7d × 6 coins of mrec raw. Signal proxy = Binance spot-lead
(conservative vs the true TWAP-60 recon — see caveat).

## 1. THE decisive finding: spot-lead is not a sufficient entry signal
Pooled 5 coins (eth/sol/xrp/doge/bnb), buy the lead-side ask, hold to
settle, fee-exact, 50sh clips, by timing × ask band:

| tl | 0.95-0.985 band | 0.985+ band |
|---|---|---|
| 40s | n=1908, 96.8%, **−$440** | n=1844, 99.0%, −$150 |
| 30s | n=1436, 97.5%, −$33 | n=1732, 99.4%, +$32 |
| 25s | n=943, 95.7%, **−$655** | n=1619, 99.3%, −$73 |
| 20s | n=586, 96.1%, −$326 | n=1279, 99.5%, +$108 |
| 14s | n=245, 90.2%, **−$621** | n=636, 99.1%, −$102 |
| 10s | n=162, 93.2%, −$252 | n=513, 99.4%, −$60 |
| 5s | n=64, 89.1%, −$106 | n=252, 100%, +$26 |

Every 0.95-0.985 cell negative; 0.985+ = zero-EV noise. The target wallet
prints 96.7-99.5% at these prices. **The whole edge = the TWAP-60
reconstruction beating spot-lead on the bars that decide (near-ties), plus
selection.** The pmTeTwapWindow=60 fix is not a detail — it IS the strategy.

## 2. Cheap band (<0.80) cannot be adjudicated offline with this proxy
"Lead-side" asks at 0.09-0.55 = bars where the MARKET disagrees with the
spot-lead sign = exactly where Binance≠TWAP divergence lives (old
binance-chainlink-divergence lesson). btc showed +$148@tl40 and bnb −$114 —
both unreliable. Win% in this band rises 12%→52% as tl 5→40 (tracking
remaining-window physics ✓ contamination signature). Only the live TWAP-60
recon sweep can price this band — it holds 62% of the wallet's profit, so
it is the sweep's most important output.

## 3. Clip size is protective, not cosmetic
At 50sh clips the 0.985+ grind is net-negative through single losses (bnb
tl14: 207/209 wins, −$34). The wallet's 8sh median caps each loss at ~$8.
Recommend keeping clips ≤10sh until the recon's true loss rate is known.

## 4. Availability curve (btc, winner-ask ≤0.999 exists)
tl40 54% of bars → tl30 39% → tl25 26% → tl20 17% → tl14 9.5% → tl5 6%.
Supply argues for evals in the tl20-40 range; accuracy argues later —
the sweep's tradeoff, now with priors.

## 5. Infrastructure added this session
hype-mrec + zec-mrec recorders DEPLOYED (vacmaker's #1 coin had no recorder;
zec unexplored). mrec1h/1d have NO RES rows (pre-fix recorders — derive wins
from post-role book, validated 88/88). Adjacent cells closed tonight with
data: mid-bar momentum-taker ⛔ all bands/coins (pooled n≈6k); 1h/1d
late-window taker ⛔ no supply (~$1.2/day, books swept).

## 6. price-aggregator delay.jsonl is NOT a settlement-grade dataset (bug #15)
13.3GB, live since Jul-31, 1Hz cl+open+full ladders — looked like the true-
signal instrument, but its `open` (aggregate open ≠ venue twap-60 strike) and
`cl` (chainlink spot ≠ twap-60 stream) mislabel 19% of bars; a circular
surface built on it showed a fake $4,500/3d cheap-winner lunch (54/55 such
bars = label errors, caught by the market-final-book referee). CONCLUSION:
the <0.80 band remains adjudicable ONLY by the live TWAP-60 recon (vacmaker
sweep) or by adding `crypto_prices_twap_sixty` values to the mrec recorder —
recommended as the recorder's next change (small: subscribe + one field).

## 7. Sweep harvest + GO-LIVE decisions (2026-08-15 ~05:55 Kyiv, this session, user order "do vacuum on 5m")
Harvested ~90 bars/coin of the paper sweep (PF_TE_EVAL × PF_TE_SETTLE, h1
recon, 8sh, +1-tick FAK model, buyable = winner-ask ≤0.98 ≥5sh):
btc(tl25): sig 70/70@≥0.5bps, 6 buyable, +$0.82 · eth(tl50): 75/75, 27
buyable 27/27 correct, **+$15.24/7.5h ≈ +$49/day** · sol(tl35): 78/80, 2
misses ON buyable bars → −$6.51 · xrp(tl20): no supply · doge(tl30): miss on
buyable → −$6.09 · bnb(tl40): 83/83, 11 buyable, +$1.53.
DECISION: **eth + bnb FLIPPED LIVE** (hype-template caps: 8sh, $10/order,
−$25/day, thresh 0.5, band 0.55-0.98; inflight trimmed to $25 each so
eth+bnb+hype cannot over-commit the shared ~$94). btc/sol/xrp/doge stay
paper (thin or negative cells; sol/doge = live demos of the asymmetry: one
wrong buyable bar erases ~10 wins). Caveats logged: 7.5h calm-overnight
regime; +1-tick fill model; the old RESTING vacuum stays dead (same 0.99
queue mintsalvage died in — do not resume btc-vacuum).

## 8. Fire-gate fix (09:35): PM_TE_MIN_COVERAGE
Live eth/bnb had 0 fires in 3.5h: the hardcoded `coverage >= 0.8`
(twapedge.py) is unreachable at eval_tl 40-50s. Now env-gated
(pmTeMinCoverage, default 0.8 — no behavior change unless set); eth/bnb run
0.5 (observed coverage 0.55-0.60 passes; still guards real RTDS gaps).
⚠️ vacmaker-session note: the paper sweep's universal fire=False is THIS
gate — sweep accuracy tables are unaffected (they read evals vs settles),
but any live flip at early eval_tl needs the knob.

## 9. zec: no market to trade (2026-08-15 ~11:10)
zec-updown-5m exists (TWAP-60, fees on) but is DEAD: liq $0-0.10, book
0.01/0.99 (98c spread), volume None; our recorder's 39,312 cur-snaps contain
1 trade. Nothing to vacuum. zec-mrec stays as a tripwire for the series ever
waking up. hype needs nothing from this session (live via vacmaker session).

## 10. Whale-cell flip + paper fleet removed (2026-08-15 ~16:10 Kyiv, user order)
Whale activity pull (299 trades 08-15, data-api /activity via pod; local curl
403s without a browser UA): he trades ALL 7 coins, median fill 0.99 (sol 71
buys med 0.99, xrp 31 ALL at 0.99, hype 55 @ 0.97-0.99), median entry T-14s
(sol) to T-5s (hype/xrp), some fills T+4..T+90 POST-close (pre-resolution
taker lifts, not restings — /trades aggressor-view settles that, VACMAKER.md).
Sub-0.80 entries are rare (6/299) but memory says 62% of his profit.
→ our sol/xrp "failures" were a different cell: earlier entry (tl20-50) +
0.98 band cap. His cell = late + 0.99.

DEPLOYED LIVE (user: "deploy them live, remove all paper traders"):
sol3/xrp3/hype3-vacmaker = whale cell: eval_tl 14, cov floor 0.7 (0.8 default
is the gate that left hype dead 13.5h — do not raise), band 0.55-0.99, thresh
0.5bps, 8sh, $10/order, -$25/day, inflight $20 each, snipe+lockbuy OFF.
Risk math at 0.99: win +$0.08, miss -$7.92 → needs >99% accuracy; T-14
coverage ~0.81 is the near-certain zone per the timing sweep. hype now has
DOUBLE live exposure (hype tl40 + hype3 tl14, same-direction signals).

REMOVED all 6 paper traders (sol/doge/xrp sweep + sol2/doge2/xrp2 tl50
probes). Their full event logs are archived at
winner-vacuum/data/paper-sweep-final-20260815/ (today's jsonl per pod +
08-14 rotated gz for sol/doge/xrp) — the 08-16 harvest reads THESE FILES,
not pods. tl50 probe final state: sol2 2/2 buyable +$1.04, xrp2 8/8 +$2.16,
doge2 6W/1L -$7.12 (tl50 did not rescue doge).

GTC-rest-past-close (user idea): NOT built. btc-vacuum died queue-starved at
0.99 GTC; the 0.99 wall is ~1.4k sh at T-3 but ~98k just after close — a
post-close rester is at the back of a 98k queue with adverse selection on
near-ties. The whale's post-close prints are TAKER scoops; that lane = the
existing snipe leg (off on the new cells for clean attribution).

## 11. eth stale-book incident + first losses (2026-08-15 evening)
17:00-20:30 Kyiv: hype took the fleet's first TWO losses (DOWN@0.86 −$6.96,
UP@0.98 5sh −$4.90, live day −$11.30) — BOTH on sub-1.0bps signals at tl40;
proposal to restore hype's original 1.0bps gate is with the user (classifier
correctly blocked an unapproved live config change). Separately eth's PM WS
book went quasi-silent ~16:14-16:29 UTC (heartbeat events=2, quote age 150s,
session=35): 6 consecutive FAKs fired at phantom stale asks → all killed
harmlessly (FAK price-capped), but the PAPER SIM "filled" those phantom asks
→ eth sim rows 16:29-17:27 UTC (incl +$2.99@0.61, +$2.05@0.73 "wins") are
FICTION — exclude from any harvest (filter: PF_TE_LIVE_ORDER matched=False
bars, or PM WS event-starved heartbeats). Fixed by pod restart 20:33 Kyiv.
Lesson for the bug ledger: sim fills must be gated on BOOK FRESHNESS (quote
age < a few s), or a dead WS quietly manufactures a winning paper day.

## 12. hype tl40 removed; fleet = 6 live (2026-08-15 ~22:05 Kyiv, user order)
hype gate was raised 0.5→1.0 (20:45) but user then removed the tl40 trader
entirely (final: 3W/2L −$11.30; events archived at
data/hype-tl40-final-20260815.jsonl — includes the two loss post-mortems:
both bets at coverage ~0.33 partial-window reads that the unobserved ⅔ of
the TWAP window reversed; VERIFY exact both bars, no data error).
hype3 (whale cell tl14, cov 0.7) is the only hype trader now — first live
trade won (5sh@0.98 +$0.10). Fleet: eth tl50 / bnb tl40 / btc tl25 +
sol3/xrp3/hype3. ⚠ crypto.secret.yaml overlay forces liveMaxOrderUsd=5 /
liveMaxDailyLossUsd=50 onto every live deploy (applied last by deploy.sh) —
whale cells carry $5/$50, morning pods $10/$25; unify decision pending.

## 13. Rename + config cleanup (2026-08-15 ~22:10 Kyiv, user order)
Version suffixes dropped: sol3/xrp3/hype3 → sol/xrp/hype (same strat, one
name per coin). Old releases uninstalled, events archived to
data/{sol3,xrp3,hype3}-final-20260815.jsonl, redeployed live as
{sol,xrp,hype}-vacmaker (whale cell: tl14/cov0.7/band≤0.99/thresh0.5).
chart/bots/ now holds EXACTLY the deployed fleet: {eth,bnb,btc,sol,xrp,
hype}_vacmaker.yaml + btc_sweeper.yaml — 43 dead experiment yamls deleted
(mintsalvage/twapedge*/vacuum/pennymint/poolfarm/doge + 3-suffix files);
each live yaml now mirrors deployed helm values (drift eliminated).
NOTE: ~15 scaled-to-0 helm RELEASES still registered (mintsalvage×6,
twapedgelive×6, btc-vacuum/pennymint/poolfarm1h) — uninstalling would
delete their PVC logs; left pending user decision. Monitor recreated for
the 6 plain names. Fleet: eth tl50 / bnb tl40 / btc tl25 (≤0.98) +
sol/xrp/hype tl14 (≤0.99). Uniform-config question answered with harvest
data: per-coin tl IS the strategy (eth's 0.20-coverage reads persist
26W/0L; the same cell measured NEGATIVE on sol/doge and lost twice live
on hype — flip-rate is coin physics, not config preference).

## 14. EVERYBAR experiment LIVE (2026-08-15 22:26 Kyiv, user order)
User: "trade every bar, occasionally get better prices; lower gates, halt
999; revert = redeploy prior version." Applied to ALL SIX: thresh 0.5→0.05
bps (fires on any nonzero read within band+coverage), halt $15→$999 (halts
effectively OFF — the babysitting session is the only stop), $5 orders
unchanged. Entry times/bands/coverage floors UNCHANGED (eth50/bnb40/btc25
≤0.98; sol/xrp/hype tl14 ≤0.99 cov0.7).
REVERT SNAPSHOT: chart/bots/revert-20260815-2225/ (six yamls + README with
the exact procedure; overlay halt was "15"). On user "revert": cp back,
sed overlay 999→15, redeploy six.
Known risk (stated to user): sub-0.5bps reads measured ~93% offline — at
0.9x asks that zone is ~EV-negative on the grind (win +$0.26 vs miss
−$4.75); the experiment's value = whether cheap-ask bars outpay the thin
grind. Watch per-coin; standing push line: combined day < −$25.

## 15. Execution fix: prewarm + retry-FAK (2026-08-16 ~11:20 Kyiv, user "Go")
No-fill investigation (11 kills since everybar start, ALL would-have-won,
≈$7-8 forgone ≈ half the realized profit, concentrated in the cheap 0.59-0.91
asks): root cause = ~450ms sign+post, dominated by py_clob_client's
per-token neg-risk REST lookup INSIDE create_order — every 5m bar = fresh
tokens, so every order paid it (warm_loop only kept the session warm; the
tick cache was already WS-patched at sign).
FIX (twapedge.py, all 6 pods since 08:21 UTC):
* prewarm_loop — get_neg_risk for both tokens at market switch (measured
  35-39ms, paid outside the hot path). PF_TE_PREWARM events.
* retry-FAK — after a kill, poll signal+book every 0.3s up to 3s
  (PM_TE_LIVE_RETRY_S/GAP_S env, defaults 3.0/0.3; deadline also capped at
  bar_end−2.5s) and re-FAK only with a validated in-band ask AND the
  estimate still same-side ≥ thresh ≥ cov-floor. PF_TE_LIVE_ORDER now
  carries attempt=N; PF_TE_LIVE_RETRY_STOP(reason=signal) on decay.
  Taker-only preserved by design — GTC resting was evaluated and REJECTED
  (survivor-bias trap: observed no-fills condition on the signal having
  held; resting bids fill exactly on flips — the btc-vacuum/mintsalvage
  death). inflight guard: only filled cost counts; a fill is never
  clobbered by a later empty attempt in bar.live.
Watch: orders-per-bar in analytics now counts retries (key by bar or filter
matched=True); fill-rate on sub-0.94 asks is the success metric (was ~60%).

## 17. Retry chase-cap fix (2026-08-16 ~20:27 Kyiv, defect in §15's retry)
xrp 17:14 UTC loss exposed it: attempt 1 saw 0.80×650sh, killed (level
swept mid-flight = flip in motion), attempt 2 re-fired at the re-read
"valid in-band ask" of 0.97 — 17c worse for the same 0.14bps whisper —
filled, lost on a +0.009 tie. A vanished-and-repriced-UP book is evidence
AGAINST the signal. Fix deployed all 6: retry may only fire at
ask ≤ orig_ask + PM_TE_LIVE_RETRY_CHASE (default 0.03). Also of note:
eth 16:24 loss (−1.13bps decisive read fully reversed to +1.07; FAK filled
9.1sh @ avg 0.50 vs seen 0.90 — big FAK price improvement = collapsing
book = candidate flip-warning signal, unstudied). Losses to date: 8
(eth×4, bnb×2, xrp×2 — btc/sol/hype clean).

## 18. Retries DISABLED (2026-08-16 ~20:40 Kyiv, user order)
Final retry ledger: 5 re-fired fills 3W/2L net ≈ −$5.7 (wins +$3.98: eth
0.76/0.98/0.66; losses: bnb 0.96 tie −$4.85, xrp 0.80→0.97 chase −$4.90)
+ 1 signal-stop that dodged −$4.93. User: "remove retries — they don't
earn much." Set PM_TE_LIVE_RETRY_S=0 on all six via pmTeLiveRetryS: "0"
(new template line, default 3.0). Code path with 0 = exact one-shot
pre-retry behavior. PREWARM KEPT (uncontested ~300ms hot-path win). The
chase-cap code stays for whenever retries are re-enabled. Retried-fill
win rate 60% vs fleet 94-96% = ledger #16 quantified live: vanished-ask
bars ARE flippier.

## 19. Retries RE-ENABLED with chase cap (2026-08-16 ~21:05 Kyiv, user)
Full postmortem (§18 was stale by two settles) changed the verdict: complete
retry ledger = 5W/2L net −$1.15, and post-chase-cap the xrp chase loss
becomes a $0 miss → go-forward ≈ +$3.75/9h (~+$10/day). Recovered-win class
= cheap vanished asks refreshing 1 tick up in 1-3s (0.61-0.76 zone, the
whale's bread-and-butter). User re-enabled: pmTeLiveRetryS: "3" all six,
chase cap 0.03 active. Lesson recorded: don't summarize a feature's PnL
while its last fills are unsettled.

## 20. Vol-conditioned ask cap + strong-signal presign (2026-08-16 ~22:0x Kyiv, user "implement")
MEASURED (2,034 settled fleet bars, rolling 6-bar mean |move|, terciles
1.9/3.4bps) — sign-hold by |signal| x vol: whisper <0.15bps: 84/81/71%
(NEVER worth 0.9x — priced 5 of first 8 losses); 0.15-0.5: 96/88/96;
0.5-1.5: 99/98.5/94.7 (high-vol 0.98 entries were −EV: bnb 18:45 loss
−1.08bps→+0.64 in high vol = the blocked cell); ≥1.5: ~100% everywhere.
eth tl50 0.5-1.5 in high vol holds only 77% — its loss engine.
DEPLOYED (all 6, ~19:00 UTC):
* dyn ask cap: bot tracks last-6-bar |move| (from its own settles);
  max_ask = CAP_TABLE[vol][sig_bucket] (low: .80/.94/.98, mid:
  .75/.86/.97, high: .65/.90/.93), band-clamped; strong ≥1.5bps → full
  band cap. Gate stays 0.05 (everybar preserved — we cap what we PAY, not
  when we look). PF_TE_EVAL now logs cap= and vol=. Warmup (<4 bars) =
  flat band cap. Env: PM_TE_VOL_BARS/LO/HI, PM_TE_STRONG_BPS.
* Strong signals sign the FAK limit AT the cap (jump-tolerant; venue
  price-improves) — enables PRESIGN: both sides signed at bar start
  (PF_TE_PRESIGN 11-96ms off hot path); strong fires are POST-only.
  Rationale: post-prewarm orders still ~480-530ms — the EIP-712 sign
  (100-300ms CPU) was the remaining bulk; strong-signal races (bnb's two
  killed big-move entries, +$4.8 sim missed) are where speed pays.
* Retry validation + fill path now use the SAME per-bet cap; chase cap
  unchanged. Paper sim inherits the cap via the fire gate (sim/live stay
  comparable).

## 21. INTERVENTION LEDGER — everything tried on this fleet (index, 08-15→16)
One line per experiment/change; details in the § given. ✅ kept ⛔ dead/reverted 🔬 measuring.

| # | when (Kyiv) | what | result | verdict | § |
|---|---|---|---|---|---|
| 1 | 08-15 ~00:00 | TWAP-60 discovery (all coins; we ran twap_thirty) | fixed the settlement recon — the foundation | ✅ | VACMAKER.md |
| 2 | 08-15 night | 6-coin paper timing sweep (tl 40/30/25/20/10/5) | eth tl50 27/27; bnb tl40 11/11; sol/doge NEGATIVE; xrp no supply | ✅ became the cell map | §7 |
| 3 | 08-15 09:35 | pmTeMinCoverage env (hardcoded 0.8 blocked early evals) | eth/bnb 0-fires fixed; hype 13.5h dead → fixed 15:22 | ✅ rule (62−tl)/59 | §8 |
| 4 | 08-15 morning | eth+bnb LIVE flip ($8 clips) | day-1 10W/0L +$4.55 | ✅ | §7 |
| 5 | 08-15 ~11:10 | zec market check (+ recheck 08-16) | book 0.01/0.99, 1.38M snaps → 0 trades | ⛔ tripwire only | §9 |
| 6 | 08-15 20:45 | hype gate 0.5→1.0 after 2 cov-0.33 losses | superseded same evening | ⛔ superseded | §12 |
| 7 | 08-15 22:0x | hype tl40 REMOVED (user) | final 3W/2L −$11.30 | ⛔ | §12 |
| 8 | 08-15 16:10 | whale cells sol3/xrp3/hype3 LIVE (tl14, ≤0.99, cov 0.7) | first trades won; but ask>0.99 blocks ~85% of fires | ✅ (supply-limited) | §10 |
| 9 | 08-15 22:10 | renames (drop *3), 43 dead configs deleted, yaml↔cluster sync | drift eliminated | ✅ | §13 |
| 10 | 08-15 22:1x | $5/order; halt $15; then EVERYBAR: gate 0.05, halt $999 (user) | 25h: ~157W/13L net −$3.6 (peak +$15.6); 96% win ≠ profit; regime table came out of it | ⛔ closed 08-16 23:18, reverted to 0.5/$15 | §14,20,22 |
| 11 | 08-16 11:20 | prewarm (neg-risk REST out of hot path) | 35-39ms at bar start; but path still ~500ms (sign) | ✅ | §15 |
| 12 | 08-16 11:20 | retry-FAK (3s, signal-checked) | full ledger 5W/2L −$1.15; disabled 20:40 on my stale −$5.7 summary; RE-ENABLED 21:05 after full postmortem (+$3.75/9h with chase cap) | ✅ (with #13) | §15,18,19 |
| 13 | 08-16 20:27 | retry CHASE CAP (0.03) after 0.80→0.97 chase loss | blocks repriced-up books | ✅ | §17 |
| 14 | 08-16 | GTC-rest instead of FAK-kill (evaluated) | survivor bias — resters fill on flips; btc 0.60 tie dodge proved it | ⛔ ledger #16 | §16 |
| 15 | 08-16 21:0x | vol-conditioned ask cap (6-bar |move|; hold-rate table 2,034 bars) | whisper 84/81/71%, 0.5-1.5 high-vol 94.7% → caps .65-.98; blocks the loss cells | 🔬 live 19:00 UTC | §20 |
| 16 | 08-16 21:5x | strong-signal (≥1.5bps) limit AT cap + PRESIGN both sides | strong fires POST-only (~100-150ms vs ~500ms); presign 11-96ms off-path | 🔬 live | §20 |
| 17 | 08-16 | sim-vs-live calibration (192 sim bets joined) | sim ±25-30%: optimistic on fills (no-fill winners), pessimistic on matched (improvement); labels exact | ✅ use 0.9× haircut | RESEARCH-LOG |
| 18 | 08-16 | whale day comparison | him +$26/$2,152 all-0.99 grind, eth avoided; us +$11/$700 | context | RESEARCH-LOG |
| 19 | 08-17 00:5x | **VACMAKER v2: recon-gated 0.991 queue-jump RESTING fleet** (user; taker fleet uninstalled, logs → data/taker-final-20260817/) | rest-sim 0.46% betrayal-on-fill +0.38%/sh best case; taker≤0.99 was −EV (2.2%) | 🔬 live | §23,24 |

Loss book (9): eth×4 (whisper/reversal at tl50), bnb×3 (2 ties + 1 reversal),
xrp×2 (tie + chase). btc/sol/hype: 0. All verified exact vs gamma.
Open builds: continuous-entry [T−20,T−3] for T−14 cells; re-entry ladder;
FAK price-improvement as flip-warning veto.

### §20 addendum — first presigned fire measured (19:38 UTC)
bnb 1.68bps: presigned=true, filled 5sh@0.98, won. BUT ms=465 POST-ONLY →
the ~500ms path was NEVER the EIP-712 sign; the POST round-trip itself is
~465ms (venue-side FAK matching + edge, Helsinki RTT is only ~25ms). My §20
attribution was wrong. Presign still correct (removes 65-96ms sign +
jitter) but the big latency is server-side — client cannot cut it further
without a different order-entry path. Race-loss mitigation therefore rests
on the retry loop + presign shaving, not on beating ~465ms.

## 22. EVERYBAR EXPERIMENT CLOSED — REVERTED (2026-08-16 23:18 Kyiv, user)
Ran 19:26 UTC 08-15 → 20:15 UTC 08-16 (~25h). Wallet $93.26 → $89.67
(**net −$3.6**; peak +$15.6 at $108.89 mid-afternoon). ~165 live fills,
~157W/13L (96% win rate — and still net-negative-to-flat: the asymmetry
in one line). Reverted to snapshot: **thresh 0.5, halt $15/coin, $5
orders**; kept from the experiment era: prewarm, retry+chase-cap (3s),
vol-conditioned ask caps, strong-signal presign, $5 sizing.
WHAT THE 25h BOUGHT (knowledge):
* Grind (0.94-0.99 asks, any signal): profitable but tiny (+$0.10-0.15/W),
  destroyed by any tie. Whisper (<0.15bps) at 0.9x: NEVER +EV (71-84%
  hold). Cheap entries (0.55-0.90): the real money AND the real losses —
  net ≈ flat over the full run; profitable in calm, toxic in US-evening
  high vol (7 losses 18:45-20:00 UTC 08-16 alone, ~−$19 off the peak).
* Species: whisper-entry (gate-fixable), decay-to-tie (gate-immune),
  full-reversal (eth tl50 specialty: 4×, even at 1.1-1.24bps — only later
  entry or eth-specific tl fixes it; eth = 7 of 13 losses).
* Regime dependence measured (notes §20 table) — now enforced in-bot.
* btc/sol/hype took ZERO live losses the whole experiment.
* First trades ever for btc (32W/0L!), sol, xrp under the 0.05 gate.
* Fill physics: median slip 0.000; FAK improvement real (0.50 vs 0.90);
  POST round-trip ~465ms is venue-side (presign shaves only the sign);
  fill rate 79-96%, misses concentrated in cheap contested asks.
Verdicts moved to ledger §21 (#10 now ⛔ closed → knowledge kept).
Post-revert bot = original 0.5-gate cell map + the entire execution stack
learned during the experiment. eth tl50 reversal risk = open question
(consider tl35-40 or a reversal-veto if its losses continue at 0.5 gate).

## 23. Favorite-betrayal rates from the recorders (2026-08-17 ~00:1x Kyiv)
Question (user): % of bars where the BOOK's favorite is ≥0.90 at T−X yet
resolves opposite. Last ~48h, 7 mrec recorders, ~3.2-4.0k qualifying
bars/cell, favorite = book mid:
  T−45: 0.92% | T−30: 0.69% | T−20: 0.27% | T−15: 0.23% | T−10: 0.23% | T−5: 0.15%
  (≥0.95 favorites: 0.59→0.13%; ≥0.98: 0.39→0.05%)
Economics: buying a ≥0.98-priced favorite at T−15 wins 99.95% vs 98%
breakeven → the pure book-favorite grind is +EV ~1.5-2%/share inside T−20
(matches the old lockbuy tiers). Time structure: betrayal drops 3.4×
from T−45 to T−20, only 1.8× more to T−5 — the safety knee is ~T−20.
Per-coin at ≥0.90: sol/xrp/hype have ZERO betrayals inside T−20 (0/~4.9k
pooled cells) → whale-cell T−14 lane is as safe as measurable. eth/btc
worst EARLY (1.2-1.3% at T−45 — eth's tl50 reversal losses are exactly
this ambient rate at 0.9x prices); bnb worst LATE (0.4-0.7% even at
T−5/10 — its tie-loss habit). Actionable: quantifies the eth tl50→tl25-20
question (ambient betrayal 1.3%→0.27%); bnb favorites deserve a wider
tie-margin than other coins. Script: scratchpad/betrayal.py (rerunnable).

## 24. VACMAKER v2: RESTING-MAKER fleet (2026-08-17 ~00:5x Kyiv, user order)
User: "uninstall old traders and deploy new version" after the §23 rest-sim.
Basis: taker-at-≤0.99 is adversely selected (betrayal 2.2% on buyable —
−EV), but a 0.991 QUEUE-JUMP bid (0.001 tick above the 0.99 wall) filled
by seller flow measured 0.46% betrayal-on-fill over 48h → +0.38%/share
best case (+$5-9/day ceiling). UNMODELED RISKS (stated pre-deploy): queue
competition at 0.991+ and size-weighted adverse selection (flips sweep
full 5sh, noise fills partial) — the two that killed btc-vacuum.
DEPLOYED all 6: pmTeMakerRestPx=0.991 on the existing twapedge maker path
(post-only; rejects=taker was available; recon-gated: rests only on
decisive ≥0.5bps + coverage; maker_loop cancels on flip or |est|<1.0bps;
fills booked at close; $5/order, $15/day halts, inflight caps). Taker FAK
lane still fires when the ask ≤ dyn_cap (maker returns first only when it
successfully rests). OLD TAKER FLEET UNINSTALLED — full event logs →
data/taker-final-20260817/ (2.5-2.7k events/coin early cells, 1.4k whale
cells). Monitor rebuilt for PF_TE_MAKER_REST/DONE/REJECT + LIVE_SETTLE.
Watch: fill rate vs sim 24%, betrayal-on-fill vs 0.46%, cancel-race
outcomes, bnb (worst measured cell 3.4% — halts are the guard).

### §24 addendum — post-only DROPPED, plain marketable GTC (00:51 Kyiv 08-17)
User correction: "not a maker — just rest a buy at 99c." _maker_rest now
posts a plain GTC at 0.991: crosses any asks ≤0.991 IMMEDIATELY at their
prices (taker), remainder rests. First 2 min of the old post-only build had
5/6 coins REJECT with would-cross on one bar — under GTC those are instant
fills, so the change materially raises fill rate. Booking hardened:
crossed portion (fill0/cost0) captured at placement; flip/decay cancel now
cancels FIRST then books ANY held shares (crossed + hit-before-cancel) into
bar.live so settles account them; close-out cost = cost0 + rest×0.991.
PF_TE_MAKER_REST logs crossed=/crossed_avg=; REJECT event retired.

### §24 addendum 2 — price-grid fix + first live cycles (00:15 Kyiv 08-17)
Venue rejected 0.991 ("invalid price, max: 0.99"): the 0.001-tick regime
only exists after a book's tick_size_change (>~0.96); at rest time ticks
are 0.01. Fix: rest px = MAKER_REST_PX rounded DOWN to the token's live
tick grid (min(cfg, 1−tick) → 0.99 now, 0.991 automatically when ticks
flip). bar.maker_px carries the actual price through all accounting.
FIRST CYCLES (bar 21:10-15 UTC): eth GTC@0.99 CROSSED 5sh @ avg 0.96
(1.23bps — the marketable half working); bnb+sol rested 5sh@0.99 clean
(bnb on a −7.4bps signal); hype full cycle rest→no fill→cancel@close $0
(MAKER_DONE fill_rate=0). Placement 67-642ms. All six on the build.

## 25. VACMAKER v3 — THE WHALE CLONE (2026-08-17 ~14:45 Kyiv, user order)
User: "I want ours to be exactly the same [as 0xefdf6abc]." His measured
machine (135 buys/9h tape + 4,085-trade forensics): acts ONLY in
[T−30,T+90]; continuous — lifts the favorite whenever ask ≤0.99 (flat cap,
$8 clips); re-enters ~2.76 clips/bar (max 6); ~20% of volume = post-close
identity scoops; all 7 coins; never rests; never enters before T−30.
DEPLOYED (all 7 pods incl NEW doge):
* whale_loop (twapedge): every 0.4s in tl∈[3,30]: recon ≥0.5bps + cov ≥0.5
  + fav ask ≤0.99 → FAK $8 clip (ask+0.01 buffer, cap 0.99, no chase);
  1s cooldown; re-enters until $16/bar ladder; PF_TE_WHALE_ORDER events
  (clip=N, spent=); settle books each clip (PF_TE_LIVE_SETTLE clip=N).
* legacy one-shot live lane OFF when whale on; paper sim still evals at
  tl28 as benchmark. Maker rest OFF (he never rests). SNIPE ON (his
  post-close lane): cap 0.99, $8, 90s window. Clips $5→$8 (overlay too).
* KEPT vs pure clone (stated to user): $15/day halts + recon gate.
* Comparison tool tools/whalecmp.py (run in-pod): joins our fills vs his
  tape per bar → BOTH/HIM-only/US-only table. Monitor rebuilt: 7 pods,
  WHALE_ORDER matched + settles + snipe fills + errors.
Risks: 0.99-cross adverse selection (2.2% betrayal on offered asks §23) is
now ACCEPTED BY DESIGN (his model) — halts are the backstop; ladder means
up to $16/bar/coin exposure (~$112 fleet-wide worst case vs $89 wallet —
inflight caps ($20-25) bind first; stagger makes this rare in practice).

### §25 addendum — settle-loop hang incident + fix (16:1x Kyiv 08-17)
12:11 UTC: ONE hung gamma urllib call (despite timeout=10) froze
settle_loop fleet-wide for ~50 min — whale fills kept landing but nothing
booked; wallet "fell" to $42 while $48 sat in unswept winning positions
(eth 3-clip DOWN won +$2.1, sol pair won; all reconciled, zero loss).
FIX (all 7): settle_loop gamma lookup wrapped in asyncio.wait_for(25s) +
per-bar try/except (a stuck bar can never freeze the pipeline again);
same guard in verify_loop; PF_TE_SETTLE_ABANDONED event when a bar with
positions is dropped after 900s (positions still redeem via sweeper —
only bot-side pnl accounting is lost). Restart cost: in-memory bars from
the frozen window never book their PF_TE_LIVE_SETTLE (halt counters
under-count that window — noted). BUG LEDGER: this is #17 —
"a single unbounded await in a for-loop is a fleet-wide freeze."

## §26 — v3 day-1 results, ladder verdict, 0.94 gate (08-17 evening) ⭐ HANDOFF

Cumulative day (MY ledger — pod counters reset on every restart; wallet is
truth): eth +14.16 (19W/0L), bnb +2.33, btc −12.59 (6W/2L), xrp +2.19,
hype **−27.59 HALTED** (8W/4L), doge +1.16, sol 0 → **≈ −$20.3**, wallet
$76.25 @ 21:57 Kyiv (reconciled to the cent vs sweeper HBs; no orphans).

THREE loss bars, one shared anatomy — ALL mid-band (seen asks 0.91/0.68,
0.85×2, 0.93×2), ALL weak-ish est (0.56–1.05bps), ALL laddered to 2 clips
(−13.57, −15.48, −15.04). btc bar had the collapse signature (ask 0.91→
filled 0.72, book being swept); hype bars were stable mid-band asks where
recon itself flipped by the bell (final TWAP +0.6 vs −0.9 at entry).
Meanwhile eth printed 19W/0L incl the SAME cheap-fill signature (+2.96
@0.72 on a 0.94 seen ask) — coin-level luck vs skill undecidable at n=30.

LADDER ANALYSIS (user asked "does the ladder pay?"): marginal clips (≥2)
20 fired: 18W (+$12.2, mostly +0.08–0.32 at 0.97–0.99) / 2L... then a 3rd
loss bar made it **net −$9.3**. At 0.99 a marginal clip needs ≥99.0% hold;
at 0.85 needs ≥85% — mid-band marginal clips are nowhere near. Clips ≥2 at
seen ≥0.94: **16/16 W**. → USER PICKED: gate ladder clips ≥2 on ask ≥0.94.

DEPLOYED 18:55 UTC (eth bnb btc sol xrp doge): `WHALE_LADDER_MIN_ASK`
(env PM_TE_WHALE_LADDER_MIN_ASK, default 0.94) — whale_loop skips
re-entry clips when `bar.whale` non-empty and ask < 0.94. Clip 1 keeps the
full MIN_ASK 0.55 band. Template line added (explicit-key map!).

⚠️ **hype NOT redeployed — deliberately.** Halted at −27.59 on OLD code;
restart would zero live_day_pnl and un-halt it 5h early. **MUST-DO at UTC
rollover (03:00 Kyiv): `cd winner-vacuum && ./deploy.sh hype live
vacmaker`** — otherwise hype self-resumes at midnight UTC on the
UNGATED build. Side effect of the 6 restarts: their $15 day budgets
re-armed (btc had only $2.4 left, now fresh).

HALT OVERSHOOT (bug-ledger-adjacent): the halt only gates NEW fires; a
2-clip bar in flight sails past it → true per-coin worst case ≈ halt +
ladder (hype: −27.59 on a $15 line). Accepted for now.

MIN_ASK floor question (user floated 0.80/0.85): today's data says those
are placebo — losing clips' seen asks 0.91/0.68/0.85×2/0.93×2, so 0.85
blocks only the 0.68 (−$6.2 of −$43.7 gross) and 0.85 keeps the 0.85 bar
(floor must EXCEED it). 0.90 blocks bar #2; 0.94 blocks all three.
**KEY RECHECK: the whale's own pre-close histogram floor IS 0.94**
(1804@0.99…41@0.94, zero below — VACMAKER.md table); his cheap fills are
the POST-CLOSE scoop lane, not pre-close mid-band. So clip-1 MIN_ASK 0.94
= the faithful clone; our 0.55 band is OUR deviation. NOT applied — user
has not decided (last word = option 2 only). Cost of 0.94 floor today:
eth's sub-0.94 winners (~+$10).

WHALE OVERLAP (3h sample, whalecmp): 7 BOTH bars (1/coin), 14 him-only,
10 us-only; same side on every shared bar; we fill earlier/cheaper (T−28
first-qualifying vs his T−11 median), he goes deeper (3–5 clips) and
takes marginal bars we gate out. Keep piping tools/whalecmp.py in checks.

Watch next: gate behavior (clip≥2 events must all show seen_ask ≥0.94),
first SNIPE fill (still zero), sol dead-quiet (2 fills all day — book
rarely offers ≤0.99 fav inside T−30?investigate), monitor b8enlux1l.

### §26b — FLIP-BAR FORENSICS: every bar that mean-reverted through us (08-17)

All three v3 loss bars, complete record (entry recon vs final TWAP-60):

| bar | coin | UTC | clips (seen→fill) | est@entry | final h1 | point | swing |
|---|---|---|---|---|---|---|---|
| 1786979100 | btc | 15:05 | T−30: 0.91→**0.72** $7.36; T−29: 0.68→**0.48** $6.21 | −1.05 | **+0.16** | +2.47 | 1.2bps |
| 1786989000 | hype | 17:50 | T−23: 0.85→0.85 $7.74; T−22: 0.85 $7.74 | −0.56 | **+0.64** | +3.67 | 1.2bps |
| 1786991700 | hype | 18:35 | T−30: 0.93→0.93 $7.52; T−27: 0.93 $7.52 | −0.91 | **+0.56** | +6.85 | 1.5bps |

Total −$44.09 gross (−$13.57 / −$15.48 / −$15.04). Shared mechanism:
1. **Entry lead < late-window vol.** Every entry est (0.56–1.05bps) was
   SMALLER than the realized last-25s swing (1.2–1.5bps). With ~46% of the
   TWAP-60 weight still unwritten at T−28, a ~1bps lead is coin-flip
   territory when the tape is moving.
2. **All three finished NEAR-TIES** (final |h1| 0.16–0.64bps) that
   resolved opposite — the same near-tie zone flagged in
   [[binance-chainlink-divergence]] as structurally unpredictable.
3. **The mid-band ask WAS the tell.** Books priced the "favorite" at
   0.48–0.93, i.e. the crowd was correctly uncertain while our recon
   pretended to know. Two sub-patterns: btc = LIVE COLLAPSE (asks swept
   0.91→0.68→<0.55 in ~2s WHILE we laddered — informed flow ran us over
   mid-execution); hype ×2 = STABLE mid-band ask, recon itself reversed
   by the bell.
4. Cross-coin: on both hype bars the OTHER coins' recons won their bars
   (btc UP✓ bnb DOWN✓ on 17:50; bnb UP✓ on 18:35) — per-coin flips, not
   market-wide regime.
5. The whale skipped all three bars (whalecmp him[0] on each) — consistent
   with his 0.94 pre-close floor + T−11 median entry: by T−11 these bars
   showed either a flipped book or no ≥0.94 qualifying ask on the doomed
   side.

Open question for the next agent: eth won 5 mid-band bars today with
similar ests — is eth's last-25s vol structurally lower (recon more
"done" at T−28), or luck? Measure per-coin late-window swing
distribution from recorders before trusting eth's mid-band lane.

## §27 — ⛔ THE 1c REVERSAL LOTTERY (buy the OPPOSING side) — CLOSED (2026-08-17)
**User question:** vacmaker buys the winner at T−14s; some bars mean-revert.
Buy the other side too — 1c × 100 shares = $1 — and cash the reversal?

**Measured** on the mrec recorders, ground truth only (no proxy signal):
6 coins × 2,550-2,742 bars = **15,658 bar-observations per tl**, 07-30→08-11.
For each bar: cur-SNAP nearest tl, cheap side = lower bid, price its best ASK
as a taker buy, EV = P(win) − ask − 0.07·ask(1−ask). Tool (rerunnable):
**`winner-vacuum/tools/cheaptail.py`** (`--rows` to re-report a saved scan).

Pooled at **tl~14s** (the vacmaker entry):
| loser ask | n | wins | win% | breakeven | hi95 | EV/sh | EV as % of premium | med size |
|---|---|---|---|---|---|---|---|---|
| 0.001 | 965 | 0 | 0.00% | 0.11% | 0.40% | −0.0011 | −100% | 928 sh |
| 0.002-0.009 | 408 | 1 | 0.25% | 0.64% | 1.38% | −0.0040 | −62% | 55 |
| **0.010** | **6106** | **11** | **0.18%** | **1.07%** | **0.32%** | **−0.0089** | **−83%** | 927 |
| 0.020 | 1153 | 18 | 1.56% | 2.14% | 2.45% | −0.0057 | −27% | 20 |
| 0.030 | 593 | 12 | 2.02% | 3.20% | 3.50% | −0.0118 | −37% | 20 |
| 0.04-0.05 | 1244 | 28 | 2.25% | 4.79% | 3.23% | −0.0254 | −53% | 16 |
| 0.06-0.10 | 1561 | 70 | 4.48% | 8.05% | 5.63% | −0.0357 | −44% | 20 |
| >0.10 | 3628 | 718 | 19.79% | 34.20% | 21.12% | −0.1441 | −42% | 10 |

**Verdict: −EV in every band at every tl (30/20/14/10/5s) and every coin.**
The 1c cell is the worst-priced of all: fair value **0.0019** (1.9 tenths of a
cent) vs the 0.010 tick floor = **5.3× overpriced**, and hi95 0.32% < the 1.07%
breakeven ⇒ +EV is statistically **excluded**, not merely unproven. Per coin at
tl14/1c: btc 2/1336, eth 4/1541, xrp 3/1211, sol 2/1250, bnb 1/1018, doge
0/1122. A $1 clip on every bar × 6 coins ≈ **−$15/day** in slow bleed.

**Why the intuition misfires.** Bars DO mean-revert — 5.55% of bars flip the
T−14 book favourite (8.60% at T−30 → 3.38% at T−5). But reversion and a 1c
price never coexist: the flip-prone bars are the ones the crowd prices
0.10-0.45, and by the time the loser is 1c the bar is decided. Conditioning on
vacmaker's own trade bars (a fav ask ≤0.99 exists) the loser is at 0.02+ on
1,071 of 1,080 bars — **the 1c lottery ticket is not even on sale there**.
Same story on our three real v3 loss bars (§26b): fav asks 0.48-0.93 ⇒ the
opposing side cost 7-52c, never 1c.

**As a hedge it is arithmetically dead too:** fav ask + loser ask at tl14 has
median **1.020**, p5 1.008, and is **<1.00 on 0.1% of bars** — pairing the two
legs is a guaranteed loss before fees (same wall as poolfarm ledger #13).

**STEELMAN also fails** — bars that only just decided (loser expensive at T−30,
crushed to 1c by T−14), which is where late reversion must concentrate:
| loser @tl30 | n | reversals | breakeven | hi95 |
|---|---|---|---|---|
| ≥0.03 | 1795 | 7 (0.39%) | 1.06% | 0.80% |
| ≥0.05 | 908 | 4 (0.44%) | 1.06% | 1.13% |
| ≥0.10 | 280 | 0 (0.00%) | 1.07% | 1.35% |
| ≥0.30 | 64 | 0 | 1.07% | 5.66% |
Late-decided bars reverse **0.39%** — worse than the 1.06% needed, hi95 0.80%
still excludes it. There is no "recently volatile" subset that pays.

**The real signal is the MIRROR, and we already trade it.** Across the whole
range the near-close cheap side wins only ~55-60% of what its price implies
(and ~19% at the tick floor) ⇒ the +EV side is **selling** that tail /
**buying** the favourite — i.e. exactly vacmaker. Consistency checks: this
matches §23 from the other side (book favourite ≥0.98 betrays 0.05-0.39%), and
the July cheap-tail falsification in [[thierrax1-leaderboard]] ("cheap tail
fair-to-OVERpriced, favourites underpriced") now extends into the settlement
window. Selling the 1c loser is +EV by ~+0.8c/share on paper — and that trade
is **mintsalvage**, which died on queue position, not on economics
(MINTSALVAGE.md §8): 900+ shares already rest at 1c, so nobody reaches the
back of that queue. Both sides of the 1c level are therefore closed: buying is
5× overpriced, selling is unfillable.

**Do not reopen** unless (a) sub-tick pricing appears — the 0.001 cell is the
only statistically open one (0/965, hi95 0.40% vs 0.11% breakeven) and it IS
reachable: the venue minimum is **5 shares, not $1** (see commons.md "venue
order limits", verified 08-17), so 5sh × 0.001 = **$0.005** per bar, and 0.001
asks exist on ~6% of bars with ~900sh offered. ⚠️ our own code would block it
(`sh*px < 1.05` guard) and the payoff is ~$1.4-3/day/coin at best — noise, not
a program; or (b) a coin appears whose late-window vol makes T−14 flips ≥1.1%,
which no coin in this dataset does. NOTE the earlier claim in this section that
$1 was a venue minimum was WRONG — it is our code's guard, undocumented at PM.

## §27 — VENUE FEES & TAKER-TIER PROGRAM (verified 08-17 vs docs.polymarket.com)

Two SEPARATE systems (conflating them = bug ledger #18):
1. **Per-market fee** (gamma feeSchedule on 5m crypto): `{rate 0.04,
   exponent 1, takerOnly, rebateRate 0.25}` → taker fee = 0.04 ×
   min(p,1−p) × shares. Negligible at 0.99 (~$0.003/clip), max at 0.50
   (2% of clip). Makers pay 0 and split the 25% rebate pool.
2. **Taker Rebate Program** (docs/programs/taker-rebates.md, live since
   2026-05-28): 7 tiers on 30-day WEIGHTED volume,
   **wV = size$ × (1−entry price) × category weight (Crypto 2.3)**.
   Tiers: $2k Bronze 3% / $20k Silver 8% / $200k Gold 18% / $1M Plat 32%
   / $4M Diamond 44% / $10M Obsidian 50% (+one-time bonuses $10/$50/…).
   Rebates accrue live, paid daily 00:00 UTC (min $1). Tier shows on the
   profile page.

OUR standing (wallet 0xdb66d896, all-time vol $104k "effervescent-
elephant"): 30d wV ≈ **$5.4k (floor) → BRONZE 3%**. Estimate from
/activity BUY rows ×2.3 (offset cap 5000 truncates at 08-03; sells and
July excluded). Composition: 08-11/12 mid-price era = $4.4k of it; v3's
0.99 clips earn ~nothing ($132 wV on $1.1k volume 08-17) — 0.99 entries
have upside 0.01, so wV ≈ vol/43. When 08-11/12 age out (~09-10) we
drift toward Tier-0 unless mid-band volume returns. DO NOT trade −EV to
farm wV: Bronze rebate = 3% of (already tiny) fees.

HOW TO CHECK: profile polymarket.com/profile/<proxy>; volume via
lb-api.polymarket.com/volume?window=all&address=<proxy> (window=1w/1m
reject the address param); /activity offset hard-caps at 5000 rows;
docs pages: append `.md` to any docs.polymarket.com URL (mintlify) or
start from /llms.txt — the rendered pages are JS-empty for curl.

## §28 — ⭐⭐ THE FLIP LOSSES SOLVED: it is ENTRY TIME × |est|, not the ask band
### (2026-08-17 late, answers the §26b open question — and refutes its hypothesis)
§26b left one question: "eth won 5 mid-band bars with similar ests — is eth's
last-25s vol structurally lower, or luck? Measure per-coin late-window swing
from the recorders." Measured, on a full fresh pull (recorders drained to
`data/mrec/`, 07-30→08-17, **28,006 bars × 6 coins**) plus every event archive
we hold (4,754 EVAL / 4,525 settled bars / 78 realised clips).
Tools: **`tools/swing.py`** (recorder swing surface) and
`scratchpad/flipdiag.py|flip2.py|flip3.py` (live-log joins).

### 1. What is still unwritten when we enter (|swing| = final TWAP − est so far)
p50/p90/p99 in bps, from the recorders:
| coin | T−30 | T−28 | T−20 | T−14 | T−10 | T−5 |
|---|---|---|---|---|---|---|
| btc | 0.24/1.18/3.10 | 0.22/1.10/2.83 | 0.15/0.76/1.87 | 0.10/0.49/1.21 | 0.06/0.32/0.80 | 0.02/0.09/0.22 |
| eth | 0.38/1.60/3.74 | 0.35/1.48/3.49 | 0.24/1.00/2.38 | 0.15/0.64/1.63 | 0.10/0.39/1.03 | 0.03/0.11/0.31 |
| sol | 0.44/1.63/3.80 | 0.41/1.52/3.43 | 0.28/1.04/2.24 | 0.18/0.68/1.44 | 0.12/0.43/0.93 | 0.03/0.12/0.27 |
| xrp | 0.44/1.61/3.71 | 0.41/1.49/3.53 | 0.27/1.01/2.36 | 0.18/0.65/1.55 | 0.11/0.41/0.99 | 0.03/0.12/0.28 |
| doge | 0.50/1.72/3.83 | 0.47/1.60/3.51 | 0.32/1.08/2.41 | 0.21/0.69/1.60 | 0.13/0.44/0.99 | 0.04/0.13/0.29 |
| bnb | 0.35/1.25/2.59 | 0.32/1.16/2.36 | 0.22/0.79/1.59 | 0.14/0.52/1.06 | 0.09/0.33/0.71 | 0.03/0.09/0.20 |
**A 0.5-1.0bps read at T−28 is inside the p50-p90 of the swing that is still to
come.** It is not a signal yet; it becomes one by T−10 (p90 0.32-0.44).

### 2. Flip rate = f(|est|, tl) — the whole loss mechanism in one table
Marginal-bucket flip rate, pooled 6 coins (recorder/Binance recon):
| \|est\| | T−30 | T−28 | T−25 | T−20 | T−14 | T−10 |
|---|---|---|---|---|---|---|
| 0.5-1.0 | 10.83% | **10.09%** | 8.50% | 5.45% | 2.22% | 0.63% |
| 1.0-1.5 | 5.40% | 4.16% | 3.00% | 2.15% | 0.39% | 0.11% |
| 1.5-2.0 | 2.42% | 2.27% | 1.64% | 0.29% | 0.17% | 0.00% |
| 2.0-2.5 | 1.22% | 0.86% | 0.58% | 0.29% | 0.00% | 0.00% |
| 2.5-3.0 | 0.72% | 0.45% | 0.19% | 0.19% | 0.00% | 0.00% |
(n≈1,450-2,100 per cell.) ⚠️ **LEVEL CAVEAT / BUG-LEDGER #18:** this uses the
recorder's Binance-spot mean as the recon; the bot recons the Chainlink TWAP-60,
which is genuinely better. Our own live logs give the same SHAPE at ~⅓ the
LEVEL: 0.5-1.0bps flips **8.9%** (13/146) at T−40+, **3.1%** (5/160) at
T−25..34, **0.0%** (0/102, hi95 3.6%) at T−14..21; 1.0-1.5bps 3.2% → 0.0% →
0.0%. **Use the proxy for shape/per-coin structure, the live logs for level.**

### 3. Our operating point vs the whale's — 17 seconds is the whole gap
Gate 0.5bps flat, fills at **T−28 median** (whalecmp §26): flip 3.1% live
(10.1% proxy) → at the 0.97 ask those bars actually offer, EV **−0.073/sh**
proxy / ≈0 live. His **T−11 median**: 0.63% proxy → EV **+0.022/sh**. Same
signal, same price, 16× the flip risk — the deviation is TIME, and it is the
one deviation §26 did not flag.

### 4. Adverse selection makes the weak cell worse than its ambient rate
Joined EVAL→outcome on **buyable** bars only (an ask existed below 1.0), all
archives, stale-eth window excluded:
| \|est\| | n | acc | 95% CI | med ask | EV/sh |
|---|---|---|---|---|---|
| 0.5-1.0 | 239 | **92.1%** | [87.9,94.9] | 0.970 | **−0.0199** |
| 1.0-1.5 | 172 | 96.5% | [92.6,98.4] | 0.980 | +0.0006 |
| ≥1.5 | 475 | 98.5% | [97.0,99.3] | 0.990 | **+0.0145** |
Ambient accuracy in the 0.5-1.0 cell is ~97% (all bars) but **92% on the bars
where someone will sell to us** — the ask exists precisely when the market
disagrees. Full |est|×band surface: EVERY band of the 0.5-1.0 row is ≤0
(0.99 −0.0097, 0.94-0.98 **−0.0270**, 0.85-0.93 +0.0027, cheaper −0.02..−0.11),
and EVERY band of the ≥1.0 rows is ≥0 with the CHEAP bands the best
(1.0-2.0 mid-band +0.0257, 2.0-4.0 mid-band +0.1032).

### 5. …and 72% of our clips live in that one −EV cell
PF_TE_WHALE_ORDER est distribution: **0.5-1.0bps = 63/88 clips (71.6%)**,
1.0-2.0 = 24, ≥2.0 = 1. Why: strong-signal bars have no buyable ask (at ≥4bps
169/182 buyable rows are at 0.99, median 0.999) — the availability trap. We are
filled where we are weakest. Realised day-1 v3 (78 joined clips): **T−25..30 =
69 clips −$18.44 (−3.6%/$); T−15..21 = 9 clips +$2.07 (+3.3%/$)** — all 6
losing clips fired at T−22..30, none later. All 3 loss bars: est 0.56-1.05 at
T−22..30, laddered ×2 → correlated within-bar doubles of a ~3-10% flip risk.

### 6. VERDICT on §26b's hypothesis and on the 0.94 floor
**eth is NOT structurally calmer — it is the second-WORST coin.** Gate needed
for ≤1% marginal flip (proxy): eth 2.0bps @T−28 / 0.9 @T−14, sol 2.3/0.9,
doge 1.8/0.8, bnb 1.7/0.6, btc 1.3/0.7, xrp 1.2/1.0 (pooled 2.0 @T−28 → 0.8
@T−14 → 0.5 @T−10; mnemonic: **gate ≈ tl/14 bps**). eth's 19W/0L mid-band day
was luck, and eth's tl50 heritage is the single riskiest cell in the fleet
(live 8.9% flip at T−40+ in the weak cell) — consistent with eth owning 7/13
of the everybar losses (§22). Within-coin control: **hype flips 2.4% (5/206) at
T−40+ and 0.0% (0/415) at T−14..21** — same coin, so it is timing, not the coin.
**The 0.94 ask floor (§26) is a proxy for the real variable and cuts the wrong
way**: it bans the strong-signal mid-band clips (the most +EV cells measured)
while leaving the weak-est 0.94-0.98 clips (n=125, −0.0270/sh, our biggest
−EV cell) fully allowed.

### 7. Candidate fixes — MEASURED, none deployed (user decision)
1. **Time-scaled gate** (the direct fix): |est| ≥ 2.0bps at tl 30-25, ≥1.3 at
   24-18, ≥0.8 at 17-12, ≥0.5 at 11-3. Kills the −EV cell without giving up
   the late lane. Per-coin variant: eth/sol strictest, btc/xrp loosest.
2. **Move the window to [3,14]** (pure whale clone; he is T−11 median). Live
   0/102 flips in the weak cell there. Cost: fewer buyable bars (T−14
   availability was 9.5-17% vs T−30 39%) — trades volume for accuracy.
3. **Ladder later, not immediately**: clips 2-3 only at a LOWER tl than clip 1,
   never at the same 3-10%-flip moment (all 3 loss bars were same-moment ×2).
4. Retire WHALE_LADDER_MIN_ASK=0.94 in favour of (1) — or keep it only for the
   weak-est band, which is the cell it was actually reacting to.
⚠️ **hype cannot be validated offline at all**: its mrec rows carry
`spot: 0.0, lead_bps: null` (HYPE is not on Binance, so `binance_state` never
warms). hype is also the fleet's worst live coin (−$27.59). Either give the
recorder a HYPE spot source (Bybit/OKX/HL) or run hype at the strictest gate
on principle — today it is flying blind offline.

## §29 — MEAN-REVERSION IN THE WEAK-EST CELL (idea noted 2026-08-18 ~09:3x Kyiv, user; investigation same session)

**The case.** The §28 −EV cell seen from the other side: bars where the book
prices the favorite 0.95-0.99 at T−30..18 while the recon signal is WEAK
(|est| 0.5-1.0bps ≈ noise). The gate proposal declines to BUY the favorite
there; this idea asks whether to BUY THE DOG there instead (mean reversion).

**Priors on file (do not re-derive):**
- Live flip anchor: 3.1% (5/160) in the weak cell at T−28 era config; §28.6
  per-cell: hype 2.4% @T−40+, eth live 8.9% @T−40+ weak cell. Proxy runs
  2-3× HOT on flips in near-tie bars (ledger #19) — proxy tables give
  STRUCTURE, live logs set LEVELS.
- §27 cheap-tail (CLOSED): UNCONDITIONAL ~1c dogs win 0.18% vs 1.07%
  breakeven = 5.3× overpriced; "flip-prone bars are priced 0.10-0.45".
  NON-OVERLAP: this idea is CONDITIONAL (weak-est only) and the dog costs
  2-5c (mirror of fav bid 0.95-0.98), sitting between §27's 1c graveyard
  and its 10-45c flip-prone zone. §27 does NOT close this cell.
- Today's live losses ARE this cell paying the other guy: bnb 02:55 bar
  (est −0.53 @T−29, fav 0.97/0.98) flipped; dog buyer made ~30-50×.
- Breakeven math (hold to RES): dog at ask a wins with prob f ⇒
  EV/sh = f − a − fee(0.07·a(1−a) ≈ 0.14c at a=0.02). f=3.1%: +EV for
  a ≤ ~0.028; f=1.3% (live CI low): −EV everywhere ≥0.015. THIN either way
  at 8sh×3c = $0.24/clip risk — the size that matters is bigger.
- Variant B — RETRACE SCALP (no flip needed): buy dog at 2-4c, sell into
  the mid-bar reversion (dog bid = 1 − fav_ask) if it prints ≥ X (0.10 /
  0.20 / 0.30), else ride to RES. Retraces are strictly more frequent than
  flips; exit liquidity mid-bar is the open question (thin books). Price
  paths in mrec are REAL (no proxy) — only the cell SELECTION leans on the
  lead_bps proxy offline.
- Relationship to the gate: complement, not either/or. Gate = stop donating
  in the cell; §29 = try collecting in it. Gate decision is independent and
  still pending (replay: gate saves net +$27.75 over the v3 era).

**Investigation plan (rev A):** single-pass local-mrec sweep (7 coins × last
7-19 days, 5m): at probe times tl ∈ {30, 25, 20} condition on fav_ask band
× |lead| bin; record dog_ask=1−fav_bid, then (i) RES-flip outcome, (ii) max
subsequent dog_bid=1−fav_ask (retrace depth), (iii) EV of hold vs scalp-X
policies with taker fees, per bin. Anchor flip LEVELS to live logs; treat
proxy-selected weak bin as ±2-3× on flip rate; retrace stats are
proxy-independent given the cell. Script: session scratchpad revmean.py,
results below when run.

**§29 RESULTS (2026-08-18 ~09:30, revmean.py, 6 coins × 7d local mrec, 2,668
probes; hype excluded — no offline recon).** ⛔ CLOSED NEGATIVE, both variants:
- HOLD-to-RES: EV −0.94…−3.03 c/sh in EVERY (ask-band × |lead|) cell. The
  target weak cell (fav ask 0.95-0.985, |lead| 0.5-1.0): flip 3.65% PROXY
  (⇒ ~1.2-1.8% true per ledger #19) vs dog ask avg 4.5c ⇒ true EV ≈ −3c/sh.
  The dog carries a longshot premium ~2-4× its true flip rate in every cell —
  the same favorite-longshot bias that makes the FAVORITE side the +EV side
  (it IS the vacmaker edge). Consistent with §27 (1c dogs 5.3× overpriced).
- RETRACE SCALP (sell dog at first bid ≥0.10/0.20/0.30, else ride): WORSE
  than holding in every cell (−2.5…−3.7c) — retraces ≥0.10 happen only
  ~12% of weak-cell bars, and capping the payoff forfeits the rare full
  flips that carry all the value. Exit liquidity wasn't even the binding
  problem; the entry price is.
Verdict: mean reversion cannot monetise the weak cell from the dog side.
The only fix for the cell remains NOT TRADING it (the §28.7 time-scaled
gate, replay +$27.75/era). Script: session scratchpad revmean.py + revout/.

## §30 — 08-19 LOSS ANATOMY + FRESH REPLAY: the gate must be PRICE-CONDITIONED
### (2026-08-19 ~18:30 Kyiv; live-log analysis, 753 settled clips 08-16→19; no deploy)

**The two 08-19 loss bars are §28's cell, exactly.** doge 10:45 Kyiv bar
(2 clips DOWN @0.99, est −1.17 @tl 29.5/28.3, cov 0.53, vol 3.47) and hype
11:20 Kyiv (2 clips DOWN @0.984/0.99, est −1.15/−1.14 @tl 27.6/26.4, cov
0.50, vol 6.90). Both flipped UP; hype's final recon margin was +0.4bps —
a true near-tie. doge's recon publicly flipped sign (−1.17 → +1.37) just
7s after clip 1; the whale_loop even bought the UP side at tl 22 (clip 3,
+$0.08) — the bot re-reads the flip fast enough, but the money was already
committed. Both bars laddered clip 2 ~1s after clip 1 (§28.7 fix #3
violated by design: same-moment doubles, again 4/4 losing clips).

**Fresh 3-day loss census (08-16→19, 753 clips, 14 losses in 8 bars):**
every loss had |est| ≤ 1.17bps AND tl 22-30 (cov .48-.55) AND
|est|/vol ≤ 0.34. Zero losses in 221 clips ≥1.5bps; zero in 74 clips
tl<20. Reproduces the §28.2/28.5 shape on the post-0.94-ladder-gate era.

**⛔ §28.7 fix #1 (price-blind time-scaled gate) REFUTED on fresh data:**
replayed on the 753 clips it cuts 614/753 (keeps 125!), forgoing $109.94
of winners to avoid all $97.21 of losses → **net −$12.72** (08-18 alone
−$19.54). The v3-era +$27.75 replay no longer holds because the fleet's
volume now lives at tl 25-30 × est 0.5-1.5 and the CHEAP mid-band winners
there pay 10-50c/clip. A price-blind margin floor buys flip-safety with
the strategy's best cells.

**✅ The surgical version — condition on PRICE: skip only when
ask ≥ 0.98 AND |est| < ~1.2-1.5bps AND tl > 20.** Unified rule:
cut when flip(est,tl) > 1 − px (break-even win prob = price). At 0.99 you
need flip <1% (needs est ≥~1.3-2.0 at T−28 per §28.2 live levels); at 0.85
you tolerate 15% and nearly everything passes — so the cheap lane must stay
open. Fresh replay of the dial (whole 753-clip window):
| gate (px≥.98 & tl>20 &) | clips cut | winners forgone | losses avoided | net |
|---|---|---|---|---|
| est<1.2 | 242 | $21.11 | $42.47 (6/6 expensive) | **+$21.36** |
| est<1.5 | 342 | $29.54 | $42.47 | +$12.93 |
| est<2.0 (no tl cond) | 525 | $45.31 | $42.47 | −$2.84 |
Per-day (est<1.5&tl>20): 08-17 −6.16, 08-18 +0.34, 08-19 +18.75 — the gate
bleeds ~$6-12/day of 9c winners on clean days and collects on betrayal
days. Region win rate 336/342 = 98.25% vs 98.83% break-even at avg px
.9883 → ≈zero-to-negative EV region carrying ALL the tail risk (today's
fleet maxDD 25.82 = these 2 bars; a −$15.8 bar also ≈ the $15 day-halt on
a flat day → hidden downtime cost). n=6 loss events — level uncertain,
shape confirmed by §28.4 (n=239 weak cell, −0.0199/sh).

**Cheap-lane losses are the cost of business, not a defect:** the other 8
losing clips (px 0.48-0.974) sit in cells §28.4 measures as +EV
(mid-band 1.0-2.0 +0.0257/sh, 2.0-4.0 +0.1032/sh); gating them donates
real winners. "Protection without losing winners" exists ONLY for the
expensive cell.

**Also re-confirmed: spaced ladder (§28.7 #3) is free money on these bars**
— clip 2 fired 1.0-1.1s after clip 1 in both; doge's signal flipped within
7s. Clip 2 only ≥8-10s later + re-pass of the gate would have saved $2.87
(doge) and plausibly $7.92 (hype) at zero winner cost measured to date.

**Status: analysis only, NOTHING DEPLOYED (user said no-code).** Candidate
config if/when approved: whale_loop extra condition
`ask≥0.98 → require |est|≥1.3 (tl>20) / ≥0.8 (tl 12-20)` + ladder spacing
≥8s with signal re-check. Data: scratchpad vac_orders.csv / vac_evals.csv.

**§30 addendum (21:05 Kyiv):** fresh xrp betrayal 20:25 Kyiv bar −$12.82
(clip1 DOWN @0.83, clip2 @0.97 est −2.07 tl 25.6 → UP won). FIRST loss with
|est|≥1.5 in the window — weakens the "zero losses ≥1.5bps" line (now
1/222). Both clips sit OUTSIDE the proposed price-conditioned gate (ask
<0.98 / strong est) in cells §28.4 measures +EV — cost-of-business class,
no gate change indicated. Day still +$40.32 incl. snipe lane's first
realized money (+$6.93, all coins).

## §31 — GATE SEARCH ON THE GATED ERA (2026-08-19 ~22:30 Kyiv; replay of live fills, NO deploy — user "no code yet")

**Correction to §30's premise:** the 0.035-slope time-scaled gate has been
LIVE since 08-18 06:30 UTC (PF_TE_START: thresh 0.5 + 0.035·max(0,tl−14),
all 7 coins; hype re-confirmed on its 08-19 08:44 restart). §30's morning
losses PASSED it by a hair (doge est 1.17 vs 1.04 needed at tl 29.5). All
replays below are era-pure: clips t ≥ per-coin PF_TE_START cutoff.

**Gated-era baseline (06:30 UTC 08-18 → 19:30 UTC 08-19, 602 joined clips,
join 602/602 clean):** whale_loop **+$57.57**, snipe +$6.93 (its first
fill), 4 loss bars only: doge 07:45 −10.8 (0.99×est1.17×tl29),
hype 08:20 −15.8 (0.98/0.99×1.15×tl27), xrp 17:25 −12.8 (0.83 cheap +
0.97×est2.07 STRONG), eth 18:55 −6.8 (0.74 cheap × est1.0). All UTC 08-19.

**Tightening replay (cut = skip clip; forgone vs saved, net Δ over era;
LOO = net after removing the single biggest saved bar):**
| candidate | cut | forgone | saved | netΔ | LOO |
|---|---|---|---|---|---|
| slope→0.05 all | 205 | 36.85 | 25.46 | **−11.39** | −22.18 |
| slope→0.06 all | 269 | 49.61 | 33.38 | −16.22 | −32.06 |
| slope→0.07 all | 316 | 55.01 | 33.38 | −21.63 | −37.47 |
| px≥.98: slope 0.07 | 261 | 22.15 | 26.63 | +4.48 | −11.36 |
| **px≥.98 & est<1.2 & tl>20** | 163 | 14.06 | 26.63 | **+12.57** | **−3.27** |
| px≥.96 & est<1.2 & tl>20 | 170 | 15.65 | 26.63 | +10.98 | −4.86 |
| clip≥2-only variants / gap<8s drop | | | | −2.96…−12.41 | |
- **Blanket slope increases are REFUTED** on the gated era — the live
  0.035 slope already sits near the volume/safety optimum.
- The best cut (expensive-thin-early, the §30 cell) is +$12.57 in-sample
  but **LOO-NEGATIVE**: the entire net rides on the one hype bar. Region
  win rate 98.2% vs 98.8% breakeven ⇒ ≈0-to-slightly-negative EV cell —
  CONSISTENT with §28.4's independent n=239 measurement (−0.02/sh), which
  is the real evidence; the 2-day replay alone cannot license it. Value =
  variance/halt-tail removal (a −15.8 bar ≈ the $15 halt on a flat day)
  at ≈0 expected cost, roughly −$7/day worst clean-day bleed.
- xrp-type (strong-est, 0.97) and eth-type (cheap-weak 0.74) losses live
  in cells §28.4 measures +EV — residual cost of business (~1-2 bars/day
  fleet-wide); no sane margin gate cuts them without eating real winners.
- Spacing-as-drop (clip2 <8s) is −EV offline; only a live delay+re-check
  A/B could rescue it (doge's est flipped at +7s — §30).

**Loosening check (blocked-but-buyable EVAL rows joined to bar results,
gated era, n=119):** est 0.8-1.05 × ask 0.96-0.99 went 40/40 (+0.0135/sh
at the EVAL snapshot ask) — upper bound ≈ +$2/day, CI includes negative,
adverse-availability makes real capture worse ⇒ **leave the gate level
alone**. The 0.5-0.8 × 0.96-0.99 cell confirms the gate: 91.2% win,
−0.072/sh (57 rows) — that cell alone justifies the slope.

**RECOMMENDATION (pending user decision, still not deployed):** keep slope
0.035; the ONLY candidate worth a live A/B is the §30 price-conditioned
skip `ask≥0.98 & |est|<1.2 & tl>20` — sold as tail/halt protection at ~zero
EV, NOT as +$6/day. Everything else measured worse than doing nothing.
Data: scratchpad vac_gated.csv (W/L/S/E/R rows, era-pure).
**§31 decision (08-19 ~23:55 Kyiv): user — "Nothing, let it run."** Config
frozen as-is (0.035 slope, no extra px-gate, no spacing change). Revisit
only if the expensive-thin cell produces a halt or the loss mix shifts.

## §32 — OVERNIGHT 08-19/20 LOSSES = VOL-REGIME SHIFT; vol-scaled entry gates REFUTED, no-ladder-in-high-vol is the one ≈free lever (2026-08-20 ~08:45 Kyiv; era-pure replay, 739 vol-joined clips; NO deploy — user "no code yet")

**What happened:** median EVAL vol tripled from ~18:00 Kyiv 08-19 (4-6bps →
14-16, p90 ~40) and stayed high overnight. Five new loss bars 01:40-07:20
Kyiv (−$53.8): eth 01:40 −15.5 (est +1.85/1.90 @0.87/0.94, vol 31.6!),
sol 02:00 −7.3 / 03:35 −15.7 (est 3.48! @0.96, vol 11) / 04:10 −7.5,
hype 07:20 −7.8. **A DIFFERENT class from §30:** real signals (1.0-3.5bps)
at mid prices (0.84-0.96) — but at 3× vol the ABSOLUTE-bps live gate is
effectively 3× looser; losers' est/vol = 0.04-0.32. sol breached the $15
halt (−21.8 w/ overshoot, parked till 00:00 UTC) — the backstop FIRED as
designed. Kyiv days: 08-18 +31.2 / 08-19 +33.5 / 08-20 −22.5 so far;
gated-era total still +42.1.

**Vol-scaled ENTRY gates: REFUTED on the full gated era.** The same
high-vol regime that produced the 5 loss bars printed MORE winner money —
every est/vol floor cuts $45-108 of winners to save $51-100:
est/vol<0.25/0.30/0.35 (tl>20) net −22.4/−20.9/−5.8; tl-scaled ratio
−20…−34; vol≥10-conditional −15.4/−8.2; best = vol≥15 & est/vol<0.30 &
tl>20 at +6.2 but LOO −9.3 (1-bar-fragile). px-conditioned ratio variants
also negative. The §31 px≥0.98 gate on updated data: +11.3, LOO −4.6,
catches ZERO of the overnight bars (d20 effect −0.3). **No entry gate
eliminates these without eating more winners than it saves.**

**The one ≈free lever — DON'T LADDER IN HIGH VOL.** clip≥2 economics by
vol band (direct cell measurement, not loss-driven): vol<10 n=254
99.2%W +$14.23; vol 10-15 n=38 97.4%W +$0.19; vol≥15 n=66 97.0%W −$0.38.
⇒ the second clip in vol≥10 is a ZERO-EV doubling of flip exposure
(97% win at ~0.97 avg px = exactly breakeven). Rule `skip clip≥2 when
vol≥10 & tl>20`: +$4.60 era net, LOO −3.3 (≈0 as expected for a zero-EV
cell), would have halved eth 01:40 and sol 03:35 (−$15.5 of tonight's
damage) and cut sol's halt overshoot. Justification = the 104-clip cell
EV, NOT the 5 loss bars — the only statistically honest change on offer.

**Verdict:** regime-driven variance, backstops worked; recommend either
nothing (halts cap the damage; vol regimes pass) or the no-ladder-vol≥10
rule as a pure variance cut at ≈$0 EV cost. All predictive gates refuted.
Data: scratchpad vac_gated2.csv.

## §33 — WHALE COMPARISON OVER THE HIGH-VOL NIGHT (2026-08-20 ~09:10 Kyiv; data-api tape 498 BUY fills since 08-19 15:00 UTC, joined to our R outcomes)

**Bottom line: same regime, +$16.57 him vs −$11.67 us (joined bars; his
excludes 52 bars missing from our R map — caveat). The difference is
TIMING, not signal quality — §28.3's "17 seconds" reconfirmed live in
high vol.**

- His fill timing in the window: **tl p25/p50/p75 = 6/15/23s** before
  close (9% post-close snipe-lane). Ours: 25-30s. His px p50 = 0.99,
  3.17 clips/bar, ~$25/bar, coins btc 117 > hype 82 > sol 81 > eth 62 >
  xrp 61 > bnb 60 > doge 35 fills.
- **Our 7 loss bars since the vol shift: he SKIPPED 5 outright** (eth
  21:55, eth 01:40, sol 02:00, sol 03:35, sol 04:10 — all our early
  T−23..30 fires on 1.0-3.5bps ests that were gone by his entry time),
  **took the OPPOSITE side on 1 and won** (hype 07:20: us UP@0.94 off a
  T−26 est +1.03; him DOWN@0.82×39sh at T−15 → DOWN won, him +$7.02),
  and **ate 1 with us 2.5× harder** (xrp 20:25 strong-signal flip: us
  −12.82, him −32.67 at 0.99×33sh — even the whale can't dodge that
  class; validates §31 "cost of business").
- **Availability myth in high vol:** §28.5 worried T−14 has only 9.5-17%
  buyable bars (low-vol measurement). This window: he found 105 tradeable
  bars at T−15 vs our 110 at T−28 — SAME volume. High vol keeps late asks
  alive; the availability penalty of the late lane largely disappears
  exactly when the late lane matters most.
- Synthesis with §32: the T−25..30 lane is fine in LOW vol (we matched
  him 08-18/19 at +31/+33/day) and toxic in HIGH vol (all 5 skippable
  losses were early fires at vol≥11). The candidate that survives both
  §32's refutations and this comparison is a **vol-conditional entry
  window** — vol≥10 ⇒ hold whale_loop fire until tl≤15 (delay, not
  skip; est gate unchanged) — NOT the refuted vol-scaled est floors.
  Offline replay can only bound it (late re-entry unobservable for our
  bars); his tape IS the live evidence the late lane works in this
  regime. Needs a live A/B if ever wanted. NOTHING deployed (user:
  no code yet).

**§32/§33 ADDENDUM — 08-20 18:50 Kyiv: the afternoon FLIPPED the cell
verdict; §32's "vol-scaled gates refuted" is RETRACTED for the delay
variant.** UTC-day 08-20 so far: **−$51.11** (11 loss bars, ALL of them
tl 23-30 × vol≥10; even est 3.5-5.9bps flipped — xrp 16:45K est −5.86 at
vol 37.6 = est/vol 0.16 = noise; 16:45K hit bnb ×3 −23.2 AND xrp −15.2
in the SAME bar = macro move ~13:47 UTC). bnb (−20.2) and sol (−21.8)
halted by the $15 backstop; eth −10.2. Balance $64.30 (≈$20-40 float
deployed). Zero VERIFY errors — signal computed correctly, its SCALE is
wrong for the regime. Union era (871 vol-joined clips) four-cell split:
| cell | n | win | pnl |
|---|---|---|---|
| vol<10 × tl>20 | 466 | 98.9% | +28.55 |
| vol<10 × tl≤20 | 71 | 100% | +8.15 |
| **vol≥10 × tl>20** | 300 | 93.0% | **−49.21** (by day +9.0/+25.1/−83.4!) |
| **vol≥10 × tl≤20** | 34 | **100%** | +12.18 |
The early-highvol cell flip-flops by day (+25 on the 08-19 trend leg,
−83 on today's chop leg) — sign is REGIME-MODE dependent (trend vs chop
within high vol), so cutting it entirely forfeits trend-day profits; but
tl≤20 in vol≥10 is 34/34 (and 105/105 all-vol tl≤20) — the late lane
never loses in either mode. OUR OWN data now confirms §33's whale
conclusion: the surviving fix is the vol-conditional DELAY (vol≥10 ⇒
whale_loop fires only tl≤15-20), not any est floor. Halt math if run
as-is: a macro chop day can bleed ~5 coins × −15..23 ≈ −$100 fleet
worst-case. Decision pending user.

**§34 — 08-20 22:55 Kyiv: VOL-CONDITIONAL DELAY DEPLOYED (user: "2,
redeploy all").** Implementation (twapedge.py whale_loop): when
`_ambient_vol() >= PM_TE_WHALE_VOL_DELAY_VOL` (10 bps, the same 6-bar
mean-|move| used by the §20 ask cap) and `tl > PM_TE_WHALE_VOL_DELAY_TL`
(20 s), an otherwise fully-eligible fire (est ≥ eff_thresh, coverage,
band, ladder budget all passed) is HELD — the loop keeps scanning and
fires normally once tl ≤ 20. Delay, not skip: no signal parameter
changed. The first blocked would-be fire per bar is logged as
**PF_TE_WHALE_DELAY** (side/ask/est_bps/tl/vol) so the counterfactual
"what the early lane would have bought" stays measurable — that event
stream vs subsequent WHALE_ORDER/SETTLE outcomes IS the live A/B §33
asked for. Params in PF_TE_START (vol_delay_vol/vol_delay_tl; verified
on all 7 pods, deployed ~19:52 UTC). Gate targets ONLY whale_loop;
snipe/lock/eval untouched. Caveats: (a) inactive until the vol window
warms (~4 settled bars ≈ 20 min after each restart) — a restart during
a high-vol burst has a blind window; (b) the redeploy reset bnb/sol
in-memory day halts (−20.2/−21.8 forgiven; fresh $15 budgets for the
rest of the UTC day) and zeroed live_day_pnl fleet-wide; (c) expected
cost per the four-cell table: forfeits early-highvol trend-day profits
(+25 on 08-19-type legs) to remove the −83 chop-day tail; late lane is
34/34 in vol≥10, 105/105 all-vol. Watch: DELAY events that later fire
late vs decay to no-fire — if most decay, the delay is a de-facto skip
and the trend-day forfeit is larger than modeled.

**§35 — 08-21 00:15 Kyiv: first live DELAY events (2/2 favorable) +
per-coin calibration of the flat-10 gate.** Live A/B so far (both xrp,
vol 23-25): bar 20:40 UTC held at tl 27.7 → fired late at tl 19.7/18.6
→ WON +2.33 (delay works as designed); bar 20:55 held at tl 21.7 (est
DOWN −1.06) → decayed to no-fire → bar settled UP, i.e. the decay
SAVED a ~$7 loss (the held signal was wrong). Era replay (854 clips
with per-clip tl + bar vol from EVAL): the flat vol≥10 gate diverts
−$44.37 of early-lane (tl>20) era PnL into the delay and keeps +$34.93
ungated. Per-coin gated-share / diverted-PnL / early-losses-caught:
bnb 5% / −22.46 / 3-of-3; btc 51% / −0.90 / 2-of-3; doge 30% / +17.38
/ 0-of-2 (!); eth 52% / −11.94 / 6-of-7; hype 92% (!) / +6.13 / 2-of-2;
sol 43% / −22.74 / 4-of-4; xrp 55% / −9.84 / 4-of-4. A relative
threshold (vol ≥ 2.5× coin-era-median) was tested and is WORSE — it
catches only 10/25 early losses vs 21/25 for flat-10 (coin vol scales
differ: hype med 19.7, eth 12.0, btc 10.0, sol 9.3, xrp 11.8, doge
6.1, bnb 3.1 — but the LOSSES cluster at absolute vol ≥10 regardless
of coin, so absolute is the right form; refutes my per-coin-threshold
hunch). Residue the gate cannot catch: low-vol marginal-est flips
(btc 08-20 20:40 vol 4.72, doge vol 3.47 — est just over eff_thresh).
WATCH ITEMS: (a) doge — the gate diverts +17.38 of pure wins and its
2 losses were LOW-vol: if doge DELAY events mostly decay, consider
exempting doge (raise its pmTeWhaleVolDelayVol); (b) hype — 92% of its
traffic is above 10, so hype's early lane is effectively OFF; its 2
era losses were caught, +6.13 kept — acceptable but the decay rate
decides. No config change this hour (2 live data points, both good).

**§36 — 08-21 01:15 Kyiv: DELAY A/B after 12 events + est/vol-ratio
exemption REFUTED.** Fates: 3 late-fires (btc/eth/xrp), all WON (+3.70
total — late asks are dear: btc's win was +$0.08 at ~0.99); 9 decays:
8 FORFEITED wins (held side won; counterfactual first-clip profit
≈ +$14.5 at the logged delay-time asks 0.57-0.99) and 1 SAVED a
wrong-side loss (xrp, ~$8). Net gate effect tonight ≈ −$10 vs no-gate
— a TREND leg, the mode where the gate is known to forfeit (era cell
still −44.37; the gate is insurance against the −83 chop mode).
Tested the obvious refinement — exempt clips with |est|/vol ≥ R from
the delay ("signal large vs regime noise") — on the 292-clip era cell:
REFUTED at every R. R=0.20 exempt lane: 35 clips, 33W-2L, **−8.82**;
R=0.30: 8 clips, −5.91 (sol lost at ratio 0.316); R≥0.40: empty. The
21 cell losses do cluster at ratio <0.16, but high-ratio wins pay
pennies (avg +0.21 — asks 0.94-0.99 when the signal is that decisive)
while any loss costs ~$7.8, so the exempt lane can't be +EV. The
win-pennies/lose-dollars asymmetry IS the cell's disease; no est-side
cut fixes it. Decays mostly happen because the late-window winner ask
exceeds the 0.99 cap (documented book-vanish effect) — so in trend
mode the "delay" behaves as a skip on juicy-entry bars (doge 0.77,
sol 0.57/0.69 forfeits) and as true delay on dear bars. Verdict:
GATE UNCHANGED; the trend-leg forfeit (~$10/night worst seen) is the
insurance premium against −83 chop days. Re-examine only if a full
week's DELAY ledger shows forfeits persistently exceeding saved+halt
value.

**§37 — 08-21 05:15 Kyiv: bnb triple-clip −23.04 anatomy + THREE fix
candidates era-REFUTED.** The bar (01:05 UTC, 1787274300): est −1.012
at tl 28.6 with eff_thresh(28.6)=1.01 — the signal sat EXACTLY on the
gate boundary; ladder fired 3 identical DOWN clips in 4s (7.68×3 =
$23.04 — the `spent>=16` check passes at 15.36, so real ladder
exposure is ~1.5×WHALE_LADDER_USD); ambient vol read 8.65 (below the
10 delay gate, burst still inflating the 6-bar mean); bar settled
h1=+0.11bps — a near-tie that went UP. Third sub-threshold burst-lag
loss bar of the day (eth 8.57, sol 5.43, bnb 8.65; −20.8 combined).
Era replays all say DON'T fix:
(a) lower delay-vol to 8: era [8,10)×tl>20 = 52 clips 51W-1L +6.01 —
today's band damage is ONE bar (LOO-fragile, §31 trap);
(b) cap ladder at 2 clips: era marginal clip-3+ = 95 clips 1L +6.01
(third clips fire on confirmed setups and PAY); cap costs more than
today's −7.68 save;
(c) require est ≥ M×eff_thresh for ladder clips: BACKWARDS — era
boundary-margin ladder clips (est<1.2×eff) are 125 clips 1L +11.82
while high-margin ladder clips are −6.94; thin-margin-at-high-tl
means a HIGH absolute est (the slope already did the filtering).
Verdict: tail event; the daily halt (bnb now −22.96, halts on next
fire attempt until 00:00 UTC) is the designed backstop. Watch item
upgraded: if a SECOND sub-10 multi-clip loss lands within a week,
revisit (a) with the larger sample. Ladder-budget semantics (~1.5×
nominal) documented as intended-behavior-by-code; era-positive.

---

## §32 — The whale gap MEASURED and CLOSED as a question (2026-08-21)

Tool: `winner-vacuum/tools/whalepnl.py <hours> [wallet] [out.json]` — scores any
wallet's 5m trades against **actual resolution** (data-api activity -> gamma
`outcomePrices`). Venue truth, not logs. Run it on both wallets and join.

72h, his `0xefdf6abc` ("TWAP-SNIPER") vs ours `0xdB66d896`:

| | bars | staked | PnL | ROI |
|---|---|---|---|---|
| him | 561 | $15,258 | +$96.52 | +0.63% |
| us  | 490 | $6,774  | +$36.68 | +0.54% |

**⭐ His dollar lead is CAPITAL, not signal.** Our ROI at his stake would be
$15,258 x 0.54% = ~$82 vs his $96. Same game, he just runs 2.25x the size.

**The 307 him-only bars are 95% capital sink:** 291 of them are >=0.98 earning
**+$9.49 on $7,973 staked (+0.13%)**. Closing that "gap" means deploying ~$8k we
do not have (program ~$94) for <$10/72h. The ENTIRE prize inside the gap is
**3 bars at <0.80 = +$32.95** (~1/day). ⇒ **DO NOT relax gates to match him.**

**Where we overlap we BEAT him:** 254 both-bars, ours +$28.54 on $3,687
(+0.77%) vs his +$32.20 on $7,285 (+0.44%). Execution is not the weak link.

His own bucket table re-confirms the 0.99 capital sink from HIS ledger:
`<0.80` 3 bars +57.8% ROI / `0.80-0.94` 6 bars +12.3% / `0.94-0.98` 26 bars
+3.4% / **`>=0.98` 526 bars +0.10%**. 6% of his bars = 86% of his profit.
Also **hype was -$48 for HIM** over the same window — our hype halt was right.

⚠️ **Analysis trap caught here:** us-only 0.94-0.98 looks like a -$12.04 leak
worth gating out. It is not — **71 winners / 4 losers, median +$0.56**; the loss
is 3 tail bars (-23.04/-15.68/-7.76) and ex-worst-3 the bucket is **+$34.44**.
A sum-based "his participation is the discriminator" test called it systematic
and was WRONG. Cutting it would burn $34 of good bars to dodge 3 disasters.
Tail, not selection — same cell as §28-31 (ask>=0.98, tl 26-30), config frozen
by user 08-19 ("Nothing, let it run"). NB one bar lost $23 > the $15 halt: the
halt is realized-daily and a single bar can blow through it.

---

## §33 — TIMING IS THE EDGE: the accuracy-vs-tl curve (2026-08-21)

**Settlement is ARITHMETIC, not prediction.** TWAP-60 = mean over [T-62,T-3]
~= 59 ticks. At tl=14s, 48 of those 59 ticks ALREADY EXIST — 81% of the final
average is locked. Measured on 4,791 archive bars, the T-14 estimator (known
ticks + last-value carry) has **mean |error| 0.025 bps and calls the SIDE wrong
1 time in 864 (0.12%)**. This is why the whale's cheap bucket wins ~100%: he is
not forecasting, he is averaging a series that is mostly already written.

**Accuracy vs seconds-left (n=4,791; near-tie = |final TWAP - open| < 2bps):**

| tl | near-tie (<2bps) | clear (>=2bps) |
|---|---|---|
| 3s | 99.9% | 100.0% |
| 8s | 99.0% | 100.0% |
| 14s | 97.2% | 100.0% |
| 20s | 94.9% | 100.0% |
| 25s | 93.6% | 100.0% |
| 30s | 90.6% | 100.0% |
| 40s | 85.8% | 99.8% |

⭐ **Clear bars are 100% at EVERY horizon — waiting buys nothing, fire early for
price. Near-tie bars decay steeply — every second of waiting is accuracy.**

**⚠️ THE LIVE VOL-DELAY GATE CONDITIONS ON THE WRONG VARIABLE.** Separation of
accuracy by candidate gate, same bars:

| tl | split by MARGIN | split by VOL |
|---|---|---|
| 14s | 2.8 pp | -0.1 pp |
| 30s | 9.4 pp | -0.3 pp |
| 40s | **14.0 pp** | **-0.6 pp** |

Margin separates by up to 14 points; ambient vol separates by ~0 (slightly
backwards). `PM_TE_WHALE_VOL_DELAY_VOL=10` is keyed on a non-discriminating
quantity. (Caveat: the vol column uses a 100ms-spot reconstruction, not the
bot's internal `vol`, so treat it as suggestive; the margin column stands alone.)

**PnL by time-left band, 230h, venue truth (`whalepnl.py` + activity tl):**

| band | US clips | win | ROI | HIM clips | win | ROI |
|---|---|---|---|---|---|---|
| tl>62 (no window yet) | 28 | 64.3% | +1.18% | **0** | | |
| tl 31-62 (partial) | 250 | 91.6% | **-0.34%** | **0** | | |
| tl 13-30 | 1296 | 96.6% | +0.21% | 2893 | 99.2% | +0.96% |
| **tl<=12** | **138** | 98.6% | **+3.76%** | **2583** | 99.1% | +1.64% |

⭐ **He fires NOTHING outside tl<=30. We put 16% of clips there and the 31-62
band LOSES money.** Our own late lane earns **+3.76% = 18x our 13-30 lane**, yet
holds only 138 clips vs his 2,583. He takes 47% of clips late; we take 8%.
Mechanism: `WHALE_LADDER_USD=16` is exhausted early in [3,30], leaving no budget
for the high-accuracy late lane. Our cheap-leg win rate 84.8% sits exactly at the
tl~40 point of the curve (median cheap fire tl=26, p90=53) vs his 94% at tl~12.

**NEGATIVE results (do not re-run):** cheap-bar arrival is NOT predictable from
news/macro timing (permutation p=0.840, observed max BELOW null mean) nor from
whole-bar realized vol (p=0.101) nor from late-minute reversal structure (six
features, p=0.47-0.99 on 1m klines — though 1m cannot resolve the last 15s, so
that one is underpowered rather than refuted). Cheap bars arrive RANDOMLY ⇒ you
must be continuously present; "trade only during window X" is not available.

Also: the live bot ALREADY reads Chainlink RTDS directly (`twapedge.py:43,1237`,
correct `twap_sixty` topic) — the Binance-proxy problem was only ever an OFFLINE
research handicap, now fixed by the mrec `cl` capture. Nothing live was mis-sourced.

### §33.1 — PROPOSED, DEFERRED BY USER 2026-08-21 ("just note this, we will try this later")

**DO NOT DEPLOY until the user reopens it.** Ready-to-run options, best first:

1. **Margin-conditioned delay** (code): clear bars (margin>=2bps) fire immediately
   for price; near-ties hold until tl<=12. Replaces the vol gate with the variable
   that actually discriminates (14pp vs ~0).
2. **Config-only**: `PM_TE_WHALE_START` 30 -> 15. No code, instantly revertible.
   Blunter (delays clear bars too, costing some price) but zero code risk.
3. **Conservative**: kill only the tl>30 lanes (the 31-62 band at -0.34% ROI and
   the tl>62 fires that have NO TWAP window). Captures the smaller half.
4. Paper A/B first via the `PF_TE_WHALE_DELAY` counterfactual lane.

Expected direction (NOT a promise — the late lane's high ROI is partly SELECTION:
opportunities surviving to tl<=12 are those the market has not corrected, so
moving the window does NOT convert tl-20 fills into tl-10 fills at the same price;
volume will drop). The whale proves the late volume EXISTS (2,583 clips vs our 138).

---

## §34 — DURATION IS SETTLED: 5m is optimal AND the shortest available (2026-08-21)

Tested whether the TWAP-taker edge ports to 15m (whale trades 5m 5,489 clips vs
**11** on 15m — effectively uncontested, so worth checking).

**Verdict: 15m is DEAD — not for lack of edge, for lack of a book.**
Validated harness (`/tmp/sim4.py` pattern: scan tl 14->3, take first ask<=0.99
with size>=5, score vs RES ground truth):

| | tradable bars | rate | ROI |
|---|---|---|---|
| BTC 5m (control) | 102 / 2,400 | 4.3% | +2.67% (>=1bps) rising to **+16.28% (>=3bps)** |
| BTC 15m | 2 / 420 | 0.5% | n/a |
| ETH 15m | 2 / 414 | 0.5% | n/a |

**Mechanism (this is the general law):** longer bars are decided by LARGER margins,
so the loser is worthless before the close, nobody bids it, and therefore **no ask
exists on the winner to lift** (`ask_none` killed 331 of 342 candidate bars).

| | median \|final TWAP − strike\| | bars <2bps (near-ties) |
|---|---|---|
| BTC 5m | 2.29 bps | **45.6%** |
| BTC 15m | 3.98 bps | 27.7% |
| ETH 15m | 4.90 bps | 24.7% |

⇒ **The edge needs near-ties, and near-ties need SHORT bars.** 5m keeps ~46% of
bars undecided at settlement; 15m only ~26%. Book presence is otherwise identical
(~52% up-ask / ~54% down-ask at tl 3-14 in BOTH durations) — so it is the margin
distribution, not liquidity per se. Probed for shorter: **no 1m or 3m markets
exist**; 5m is the floor. Duration question CLOSED — we are already optimal.

### ⚠️ TWO SIM BUGS, both caught only by the CONTROL (bug ledger #13, #14)

The 5m control is known-profitable live. Any harness scoring it NEGATIVE is broken.

* **#13 — wrong strike.** Used spot-at-open as the settlement reference. The real
  strike is **TWAP at bar open** (`twapedge.py:566`, `rtds_state.twap_at(SYM, ws)`),
  i.e. mean over [ws-62, ws-3]. Symptom: control read 87.8% win at ask 0.980 ⇒
  **-2.40% ROI**, contradicting live. Also: the strike window lies BEFORE the bar,
  so a per-bar keyed series cannot see it — build ONE continuous per-coin series.
* **#14 — single-snapshot sampling.** Took `bk[-1]` (one snapshot) instead of
  scanning the whole tl window as the live loop does. A single snap carries an ask
  on a given side only ~52% of the time, so this fabricated `ask_none` at 97% and
  reported 15m as untradeable for the WRONG reason. Always scan the window.

After both fixes the control is positive AND monotone in the margin gate
(79.4%/+2.67% at >=1bps -> 100%/+16.28% at >=3bps), which is the signature of a
sound harness — the gate ordering is a free validity check, use it.
