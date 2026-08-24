# vacmaker — the TWAP-taker lane (reverse-engineered from 0xefdf6abc…)

Started 2026-08-15 ~00:00 Kyiv. Target: reproduce wallet
`0xefdf6abc3ef35f93c2753c4d36f3e17fdfb87ea5` ("TWAP-SNIPER"): **+$1,358.90
all-time on a ~$95 bankroll**, 6,124 predictions, steadily up for a year.

## What that wallet measurably does (3,000 trades + 2,000 activity rows)
| | value |
|---|---|
| side | 1,499 BUY / 10 SELL — buy-only |
| price | 1804 @0.99, 580 @0.98, 141 @0.97, 82 @0.96, 39 @0.95, 41 @0.94 |
| entry | **T−14s median**, 83% pre-close (p10 −26s, p90 +4s) |
| size | **$7.78 median, $16 max**, 8 shares typical |
| rate | **871 trades/day = 43% of all bars**; 7 coins |
| coins | HYPE 299 > BNB 288 > SOL 249 > DOGE 238 > **BTC only 172** > XRP 167 > ETH 96 |
| economics | ~0.5–1%/deployment × **~65× bankroll turnover/day** = velocity, not edge size |

**STATUS 2026-08-17 22:20 Kyiv:** v3 clone LIVE 7 coins (day-1 ≈ −$20.3 —
3 mid-band laddered loss bars vs eth 19W/0L; wallet $76.25). Ladder gate
0.94 shipped on 6; hype halted −$27.59, redeploys at UTC 00:00. NOTE the
price table above: his pre-close floor is 0.94 — full handoff in
docs/vacmaker-offline-notes.md §26 + docs/README.md §2.

**It is a TAKER strategy.** data-api `/trades` is aggressor-view (makers are
invisible there), so 3,000 BUY rows = 3,000 taker lifts.

## ⚠️ THE BIG INFRASTRUCTURE FIND
**Every coin now settles on a 60-SECOND TWAP** —
`cryptoMarketConfig.twapLookbackSeconds: 60`, id `<coin>-5m-twap-60`,
resolution source `…/hype-usd-twap-60s-streams`. Verified live on all 7 coins.

Our bots still subscribed to `crypto_prices_twap_thirty` and assumed the
`[T−32, T−3]` window — i.e. **they were reconstructing the wrong settlement.**
That is a prime suspect for why mintsalvage went flat. Fixed by
`pmTeTwapWindow: "60"` → `crypto_prices_twap_sixty`, window `[T−62, T−3]`.
Side effect: at T−14s a 60s window is **~81% elapsed** (vs 62% on a 30s
window), so the read is *more* determined early than we assumed.

RTDS carries all of `btc,eth,sol,xrp,doge,bnb,hype,zec /usd` on BOTH topics at
1Hz. (`zec` is a coin we do not trade at all — worth a look later.)

## My error, recorded so it is not repeated
First live run used `pmTeThreshBps=2.0`. All 6 evals showed the winner ask at
**0.999 or absent**, and I concluded "no ask exists ⇒ it must be a maker
strategy" and built a post-only resting mode. **Wrong.** A 2 bps gate only
selects bars the market has *already solved*, so of course the book sat at
0.999. That was an artifact of my own threshold, not a property of the venue.
The edge must live on bars where our TWAP read is decisive but the BOOK is
still uncertain — precisely the 0.94–0.99 histogram above.
(The maker mode remains in `twapedge.py` behind `PM_TE_MAKER_REST_PX`,
**default 0 = off**, so no existing bot changed behaviour.)

## Why our previous attempts failed
* **btc-vacuum** rested a 0.99 GTC bid → queue-starved. Matching inside a price
  level is SIZE-weighted, and I measured the btc/hype 0.99 wall growing from
  ~1.4k shares at T−3s to **~98k just after close**.
* **twapedge** fired at T−4.5s, by which point 89% of bars have no winner-ask.
* **mintsalvage** is btc-only (the most contested coin) and signals off a
  Binance spot lead (~71% on near-ties) instead of the exact RTDS series.

## Live state
* `hype-vacmaker` **LIVE** — taker FAK, T−14s, thresh 1.0bps, ask 0.80–0.99,
  8 sh (~$8), caps $10/order + $25/day. Snipe + lockbuy legs OFF for clean
  attribution.
* `{eth,bnb,sol,doge,btc,xrp}-vacmaker` **PAPER** — a **timing sweep**:
  eval_tl = 40 / 30 / 25 / 20 / 10 / 5 s, thresh 0.25bps. Paper still logs the
  real book ask at eval time and the real settlement, which is the entire
  measurement.
* All other trader bots undeployed (mintsalvage scaled to 0). Recorders and
  `btc-sweeper` kept (sweeper only redeems/merges, it does not trade).

## The question the sweep answers
Buying at ask `p` needs accuracy > `p`. So we need the band where
**accuracy(T−x, |est|) > ask(T−x)** with a real ask size. Two curves move in
opposite directions as x grows: accuracy falls (less of the TWAP window
elapsed) while ask availability rises (book less certain). The optimum is
wherever they cross. `scratchpad/vm_measure.sh` prints both.

First 7 matched bars (all |est|≥2bps, hype, T−14s): **accuracy 7/7 = 100%,
buyable-ask 0/7**. Consistent with the error above — need the low-|est| and
earlier-entry cells to find liquidity.

## ⭐⭐ THE DECISIVE MEASUREMENT (2026-08-15, 4,085 resolved trades)
Resolved the target wallet's buys by matching each BUY to a REDEEM on the same
(conditionId, outcomeIndex). Validation of the method:
* **97.4% of bought markets have a redeem** (1,380/1,417) — one redeem covers
  every buy on that bar, which is why a raw redeem:buy count ratio looks low.
* Win rate is **flat at 97.0-97.2% across settling cutoffs from 30m to 8h** —
  no settling-time bias.
* Computed from SHARES (cost = px x shares, payout = shares on a win). 2.8% of
  rows have `usdcSize != px*size` (fee-inclusive), so dollar fields are unsafe;
  share arithmetic is the correct basis.
*(gamma PURGES closed updown markets within ~an hour — slug lookup returns []
even for one the bot fetched minutes earlier — so redeem-matching is the only
way to resolve historical updown outcomes.)*

| entry px | n | win% | cost | payout | net | **%/$** |
|---|---|---|---|---|---|---|
| **<0.80** | 105 | 82.9% | $348 | $708 | **+$359.72** | **+103.3%** |
| 0.80-0.95 | 114 | 99.1% | $846 | $931 | +$85.07 | +10.1% |
| 0.95-0.97 | 92 | 96.7% | $704 | $711 | +$6.71 | +0.9% |
| 0.97-0.985 | 573 | 99.5% | $4,356 | $4,435 | +$78.31 | +1.8% |
| 0.985-1.00 | **3,201** | 97.0% | **$21,057** | $21,106 | +$49.23 | **+0.23%** |
| **TOTAL** | **4,085** | **97.06%** | $27,312 | $27,891 | **+$579.04** | **+2.12%** |

**THE REAL STORY — and it is NOT "buy the winner at 0.99".**
* The 0.985-1.00 grind is **77% of their deployed capital for 8% of their
  profit** (+0.23%/$, thin enough that fees/slippage nearly erase it).
* **62% of all profit comes from 105 trades below $0.80** (+103%/$), where the
  book prices the TWAP-implied winner CHEAP and our reconstruction says it is
  actually winning. Only 2.6% of their trades, and just 82.9% accurate — but
  the multiplier does the work.
* So the strategy is **not** "grind near-certainties"; it is "mostly grind at
  ~breakeven, and win big on the rare bars where the book is badly wrong."

⚠️ **Correction to my earlier note in this file:** I first reported the
>=0.985 band as NEGATIVE (-3.1 pts). That came from dollar-weighted fields and
a smaller sample; on 4,085 share-based rows it is marginally **positive**
(+0.23%/$). The actionable conclusion is unchanged — that band is a capital
sink, not an edge — but the sign was wrong and is corrected here.

**Per-coin (share basis):** Hyperliquid wins only **87.6%** — their WORST
accuracy — yet earns +10.5%/$, because its entries are cheap. Dogecoin is
negative. So HYPE is not "the reliable coin"; it is the coin with the most
mispriced cheap entries. Bitcoin/Ethereum win 100% but earn +2.1%/+1.9% — the
near-certain grind, i.e. the capital sink.

## Current fleet
| bot | mode | eval | ask band | thresh |
|---|---|---|---|---|
| hype-vacmaker | **LIVE** $8 clips, $10/order, $25/day | T−14s | 0.55–0.98 | 1.0bps |
| eth / bnb / sol / doge / btc / xrp | paper | T−40/30/25/20/10/5s | 0.55–0.98 | 0.25bps |

The paper fleet is a **timing sweep**: accuracy falls as entry moves earlier
(less TWAP window elapsed) while ask availability and margin rise. The optimum
is where accuracy(T−x) still clears ask(T−x). `scratchpad/vm_measure.sh`
prints both curves.

## What to do next (ordered)
1. **Read the timing sweep** (`scratchpad/vm_measure.sh`). It answers the one
   open question: at which T−x does a *buyable* winner-ask exist, and is the
   TWAP read still accurate there? Accuracy falls as x grows (less of the 60s
   window elapsed) while ask availability and margin rise — trade at the cross.
2. **Hunt the cheap band, not the 0.99 grind.** 62% of the target wallet's
   profit came from 105 trades below $0.80. Our fleet band is 0.55–0.98 for
   exactly this reason. The 0.985+ zone consumed 77% of their capital for 8%
   of profit and is fee-sensitive enough to be a trap at our size.
3. **Do NOT scale the near-certain grind.** At $8 clips the 0.99 lane earns
   ~2c/trade before fees; the taker fee at 0.99 is ~0.069c/share (~7% of the
   gross). It cannot pay for itself at our bankroll.
4. Re-check `zec/usd` — it is on the RTDS feed and we have never traded it.
5. Once a cell shows accuracy > ask with real depth, flip that coin live at $8
   clips and hold the $25/day cap until it has 100+ resolved bars.

## Standing lessons from this session
* **A gate that is too strict hides the edge.** thresh=2.0bps only surfaced
  bars the market had already solved (ask 0.999/absent), which nearly led me to
  rebuild the strategy around the wrong mechanism.
* **`/trades` is aggressor-view** — presence there proves TAKER, and no maker
  fill ever appears. That single fact settles order-type questions.
* **gamma purges closed updown markets fast**; resolve historical outcomes by
  redeem-matching, never by slug lookup.
* **`usdcSize` is fee-inclusive on ~3% of rows** — always compute PnL from
  shares (cost = px × shares, payout = shares on a win).
* **Always `source` .dev-env-source by ABSOLUTE path.** A relative source from
  a subdirectory silently retargets kubectl and makes live pods look deleted —
  it cost me a false "the pod is gone" alarm here.

## Timing sweep — FIRST RESULT (2026-08-15 ~00:45 Kyiv, 20 matched bars)
Small n, but the two effects are unambiguous and they agree with the target
wallet's own trade distribution.

**1. Buyable asks exist ONLY at LOW |est|.**
| \|est\| bps | bars | accuracy | buyable | med ask | EV@ask |
|---|---|---|---|---|---|
| 0.5–1.0 | 2 | 100% | 1 | 0.950 | **+5.26%** |
| 1.0–2.0 | 5 | 100% | 2 | 0.980 | **+4.71%** |
| 2.0–4.0 | 7 | 100% | **0** | – | – |
| 4.0–8.0 | 3 | 100% | **0** | – | – |
| 8.0+ | 3 | 100% | **0** | – | – |
Above ~2bps the book has already repriced and there is nothing to buy. This is
the direct confirmation that my original 2.0bps gate was self-defeating.

**2. Earlier entry = more liquidity.**
| coin | eval | bars | acc | buyable% | med ask |
|---|---|---|---|---|---|
| eth | T−40 | 2 | 100% | **100%** | 0.950 |
| bnb | T−30 | 2 | 100% | 0% | – |
| sol | T−25 | 2 | 100% | **50%** | 0.980 |
| doge | T−20 | 2 | 100% | 0% | – |
| **hype** | **T−14** | **8** | 100% | **0%** | – |
| btc | T−10 | 2 | 100% | 0% | – |
| xrp | T−5 | 2 | 100% | 0% | – |

T−14 is 0/8 on hype — **definitively too late**. Accuracy is 100% everywhere so
far, but n is far too small to price the accuracy/earliness tradeoff.

TWAP-window elapsed at each entry (window `[T−62,T−3]`, 59s long):
T−50 → 20% · T−40 → 37% · T−35 → 46% · T−30 → 54% · T−25 → **63%** ·
T−20 → 71% · T−14 → 81%. Earlier buys liquidity at the cost of certainty.

**Actions taken:** live hype moved to **T−25s, thresh 0.5bps, band 0.55–0.98**
(63% of the window elapsed — still the majority — and where sol found a
buyable 0.98). Sweep refocused on the productive region, dropping the dead
late cells: eth T−50 · bnb T−40 · sol T−35 · doge T−30 · btc T−25 · xrp T−20.
The open question is now purely **where accuracy breaks down as we move
earlier** — that is what the refocused sweep measures.

## ⭐⭐⭐ ACCURACY-vs-ENTRY-TIME, measured on 4,057 of their trades
This settles the accuracy/earliness tradeoff without waiting for our own data.
All entry windows are profitable, but the return is carried by CHEAP entries,
and the cheap entries get *cheaper and better* the LATER you go — including
after the bell.

**All entries:**
| window | n | win% | med px | %/$ |
|---|---|---|---|---|
| T−35..−25 | 168 | 98.8% | 0.980 | +4.07% |
| T−25..−18 | 175 | 91.4% | 0.990 | +1.42% |
| T−18..−12 | 1544 | 96.6% | 0.990 | +1.26% |
| T−12..−6 | 939 | 96.7% | 0.990 | +2.26% |
| T−6..0 | 530 | 97.4% | 0.990 | +3.21% |
| T+0..+120 | 701 | 99.1% | 0.990 | +2.57% |

**Restricted to px < 0.97 — where the money is:**
| window | n | win% | med px | **%/$** |
|---|---|---|---|---|
| T−35..−25 | 49 | 98.0% | 0.950 | +9.71% |
| T−25..−18 | 16 | 87.5% | 0.880 | +0.63% |
| T−18..−12 | 96 | 96.9% | 0.940 | **+14.33%** |
| T−12..−6 | 57 | 91.2% | 0.850 | **+31.88%** |
| T−6..0 | 64 | 82.8% | 0.723 | +26.18% |
| **T+0..+120** | **25** | **100.0%** | **0.640** | **+115.35%** |

**THE BEST CELL IS POST-CLOSE.** After the bell, stale offers still sell the
winner at a 0.640 median and it wins 100% (n=25) — because once the settlement
tick lands the outcome is an IDENTITY, not an estimate. This is the twapedge
`snipe` leg, which I had switched OFF (`pmTeSnipeCap: 0`) for clean
attribution — a costly bit of tidiness.

⚠️ This also **partially reverses** [[settlement-snipe-edge]], which recorded
the post-close winner-snipe pot as **$0** on 2026-08-11. That was measured on
the 30s-TWAP regime; under the 60s TWAP the pot is demonstrably alive. Re-open
that verdict.

**Applied to live hype:** eval moved T−25 → **T−10** (their +31.9%/$ cheap
cell) and the **post-close snipe re-enabled at cap 0.85** (vs the 0.10 default,
which was far below their 0.640 median), $8/order, 120s window.

Note the shape: win rate FALLS as you go later (98.8% → 82.8% pre-close) while
price falls much faster (0.98 → 0.72), so return per dollar RISES. Optimising
for accuracy is exactly the wrong objective — that is what drove me to a 2bps
gate and 0 fills. Optimise for **(win% − px) / px**.

## ⭐ POST-CLOSE SNIPE, tuned on 701 of their post-close buys
The entire post-close edge is a RARE CHEAP TAIL. Their 676 buys at 0.96+ are
worth almost nothing; 24 buys below 0.96 carry everything, at a 100% win rate
(the outcome is an identity once the settlement tick lands).

| post-close px | n | win% | %/$ | **cumulative if capped here** |
|---|---|---|---|---|
| 0.00–0.20 | 3 | 100% | +9900% | +9900% |
| 0.20–0.40 | 5 | 100% | +352% | +586% |
| 0.60–0.80 | 7 | 100% | +59% | **+226%** |
| 0.80–0.90 | 3 | 100% | +15% | +182% |
| 0.90–0.96 | 6 | 100% | +11% | +115% |
| **0.96–1.00** | **676** | 99.1% | **+0.24%** | +2.57% |

By lag after close, everything is ~100% win at a 0.990 median; the +0..+3s cell
is the richest (+5.34%/$) and 526 of 701 land inside +8s. So the WINDOW is not
the lever — **the CAP is**. Capping at 0.80 yields +226%/$; letting it run to
1.00 dilutes to +2.57%.

**Applied fleet-wide: `pmTeSnipeCap 0.80`** (the twapedge default of 0.10 was
far too tight — it would catch only the 3 deepest trades; 0.96+ is a trap that
looks like volume but pays 0.24%).

Post-close volume is spread across all coins (btc 136, hype 120, bnb 109,
sol 109, doge 95, eth 79, xrp 53) — unlike the pre-close leg, this one is NOT
alt-specific, so it should scale to the whole fleet.

## Discipline note
After this change: **stop retuning and let it collect.** Several `SNIPE_SKIP
reason=no_tick` events were self-inflicted — the skip fires when the tick OR
the bar's STRIKE is missing, and repeated redeploys kept killing pods before
they could capture a bar's opening strike. The fleet needs uninterrupted bars
more than it needs another parameter tweak.

## SNIPE_SKIP "no_tick" — DIAGNOSED (2026-08-15 ~01:20 Kyiv)
14 consecutive snipe skips looked like a feed bug. It was not.

I first probed the RTDS feed directly: `crypto_prices_twap_sixty` delivers a
**contiguous 1Hz series with ZERO missing seconds** for all 8 symbols
(hype included) over a 75s window. So the tick was never the problem.

Added the missing detail to the event, and it answered immediately:
```
PF_TE_SNIPE_SKIP reason=no_strike tick=56.217 strike=None
                 twap_ct=231 end=1786746000 bar_ws=1786745700
```
`tick` present, **`strike` None**, and `twap_ct=231` is the smoking gun: the
tick cache only held 231 seconds, so it could not reach back to that bar's
OPEN. **Every redeploy wipes the RTDS cache**, and the strike is read from the
tick stamped exactly at bar open — so a pod that restarts mid-bar can never
snipe the bar it restarted in, nor the one before it.

**The skips were self-inflicted by my own retuning cadence.** Lesson recorded:
after any vacmaker deploy, the first ~2 bars produce no strike and therefore no
snipe; judge nothing until the pod has ≥2 clean bars of uptime. The generic
version: *when a bot reads a value stamped at a boundary, a restart costs you
the whole boundary, not just the missing seconds.*

Diagnostic left in place (`reason` now distinguishes `no_tick` vs `no_strike`,
and logs `tick`, `strike`, `twap_ct`) — it cost one deploy and would have saved
several.

**Live eval moved T−10 → T−30**, reconciling two datasets: the offline surface
(other session) puts winner-ask availability at **tl30 39% vs tl10 ~6%**, and
the target wallet's T−35..−25 cheap cell wins **98.0% at 0.950 for +9.71%/$**.
Expected value per BAR = availability × return favours T−30 (~+3.8%/bar) over
T−10 (~+2.2%/bar), despite T−10 having the richer per-trade return.

**Now frozen — no more parameter changes until the fleet has hours of
uninterrupted bars.**

## Sweep at 61 matched bars (2026-08-15 ~01:40 Kyiv) — two hard results
**1. Genuine ties are coin flips, and they are the one LOSING band.**
| \|est\| bps | bars | accuracy | buyable | med ask | EV@ask |
|---|---|---|---|---|---|
| **0.0–0.5** | 4 | **50.0%** | 3 | 0.770 | **−10.31%** |
| 0.5–1.0 | 5 | 100% | 3 | 0.950 | +4.90% |
| 1.0–2.0 | 10 | 100% | 5 | 0.950 | +4.82% |
| 2.0–4.0 | 9 | 100% | 0 | – | – |
| 4.0–8.0 | 19 | 100% | 0 | – | – |
| 8.0+ | 14 | 100% | 0 | – | – |

The sub-0.5bps band is where the book DOES offer cheap (0.770 median, 3 of 4
bars buyable) — precisely because it is a genuine tie and the market knows it.
Buying there is −10.31%. **`thresh 0.5` is validated as the floor**, and this
is the trap that would have eaten a naive "just buy anything cheap" rule.
The tradable window is **0.5–2.0bps: 15 bars, 100% accurate, 8 buyable at a
0.950 median, ~+4.9%.** Above 2bps the book is always already repriced.

**2. Availability by entry time, with usable n.**
| entry | bars | acc | buyable% | med ask | EV/bar |
|---|---|---|---|---|---|
| eth T−50 | 8 | 88% | **62%** | 0.870 | ~0.7% |
| **bnb T−40** | 8 | **100%** | **38%** | 0.950 | **~2.0%** |
| sol T−35 | 9 | 100% | 11% | 0.980 | ~0.2% |
| doge T−30 | 8 | 100% | 0% | – | – |
| btc T−25 | 8 | 88% | 12% | 0.970 | ~0.4% |
| xrp T−20 | 8 | 100% | 0% | – | – |
| hype T−10 | 12 | 100% | 8% | 0.940 | ~0.5% |

Availability rises monotonically as entry moves earlier (8% at T−10 → 62% at
T−50), matching the other session's offline surface (tl5 6% → tl40 54% on btc).
Accuracy holds at 100% back to T−40 and first cracks at T−50 (7/8) — so **T−40
is the frontier**: the earliest entry that has not yet lost certainty, with the
best expected value per bar (38% × +5.3%).

**Live hype parked at T−40 and FROZEN.** I had moved it T−14→T−25→T−10→T−30
chasing each new datapoint; every move wipes the RTDS cache and costs the next
two bars' strikes. Parking beats optimising here.

Note the paper fleet still runs the pre-diagnostic build, so its SNIPE_SKIP
rows are the old undifferentiated `no_tick` label — deliberately NOT redeployed,
because uninterrupted bars are worth more than the better label.

## Snipe "skips" are mostly NOT failures — the cheap tail is just rare
Follow-up on the diagnosis above. The eth paper pod has 40min (8 bars) of
uptime and logged only **3** SNIPE_SKIP rows, not 8 — so the loop runs fine on
most bars; it simply finds no ask at or below the 0.80 cap and moves on quietly.

That is the expected rate, not a bug. In the target wallet's own history only
**24 of 701 post-close buys (3.4%)** were below 0.96, and our cap is tighter
still. At 7 coins x 288 bars/day = ~2,016 bars/day, a ~3% hit rate implies
roughly **60 cheap-tail opportunities per day fleet-wide** — but ~0 in any
given hour. **Do not read a quiet hour as a broken leg.**

Corrected split of the earlier 14-17 skips: the hype ones were genuine
`no_strike` from my redeploys (proven by `twap_ct` being younger than the bar);
the paper-fleet ones are the old undifferentiated label on bars that mostly had
nothing cheap to buy.

## Status at freeze (2026-08-15 ~02:00 Kyiv)
* 62 matched bars, accuracy 100% in every band at or above 0.5bps; the only
  losing band is the sub-0.5bps tie zone (50%, −10.31%).
* Tradable window confirmed: **0.5–2.0bps, buyable ~53% of the time at a 0.950
  median, ~+4.9%**.
* `hype-vacmaker` LIVE parked at **T−40** (best cell: 38% buyable, 100% acc).
* Paper sweep continues at T−50/40/35/30/25/20 with the snipe leg armed at 0.80.
* No live fill yet. Both legs are rare-by-design: the pre-close leg needs a
  0.5–2.0bps bar WITH an ask (~53% of ~24% of bars), the post-close leg needs
  the ~3% cheap tail.

## ⚠️ CORRECTION at 73 bars — the tie-band claim REVERSED
At 62 bars I reported the sub-0.5bps tie band as a proven trap: 4 bars, 50%
accuracy, **−10.31% EV**. Eleven bars later it reads **6 bars, 66.7%, +13.64%**.
Two additional observations flipped the sign.

**That claim should not have been stated as a finding at n=4.** The tie band is
UNRESOLVED, not negative. Keeping `thresh 0.5` is still the prudent default —
a coin-flip band cannot be priced from 6 bars either — but the justification is
"unmeasured", not "measured negative".

What HAS held up as n grew (15 → 19 bars) is the tradable window:
**0.5–2.0bps, 100% accuracy, 10/19 buyable at a 0.95–0.96 median, ~+4.5–4.9%.**
Stability across a sample increase is the only reason to trust it more than the
tie-band number.

## Availability is coin-specific, not just time-specific (73 bars)
| coin | entry | bars | acc | buyable% | med ask |
|---|---|---|---|---|---|
| eth | T−50 | 9 | 89% | **67%** | 0.930 |
| **bnb** | **T−40** | 10 | 100% | **30%** | 0.950 |
| **hype** | **T−40** | 12 | 100% | **8%** | 0.940 |
| sol | T−35 | 11 | 100% | 18% | 0.980 |
| doge | T−30 | 10 | 100% | 0% | – |
| btc | T−25 | 10 | 90% | 10% | 0.970 |
| xrp | T−20 | 11 | 100% | 9% | 0.410 |

**hype and bnb sit at the SAME T−40 and differ 8% vs 30%.** So the coin matters
as much as the clock, and hype — the wallet's #1 coin by volume — is currently
our worst for ask availability. Two readings of that: (a) 12 bars is noise, or
(b) hype's book genuinely thins earlier and the wallet's 299 hype fills come
from a different part of the bar than we are sampling. Do not switch the live
coin on 12 bars; let bnb/hype accumulate at matched T−40 and compare.

xrp printed a 0.410 median ask at T−20 — worth watching, almost certainly n=1.

## ⭐ 118 MATCHED BARS — the decision rule, and why hype@T−40 is the right cell
| \|est\| bps | bars | accuracy | buyable | med ask | EV@ask |
|---|---|---|---|---|---|
| 0.0–0.5 | 7 | 71.4% | 5 | 0.770 | +11.11% |
| **0.5–1.0** | 13 | **100%** | 7 | 0.970 | **+5.11%** |
| **1.0–2.0** | 27 | **100%** | 12 | 0.970 | **+4.53%** |
| **2.0–4.0** | 20 | **95.0%** | 3 | 0.990 | **−32.43%** |
| 4.0–8.0 | 29 | 100% | 0 | – | – |
| 8.0+ | 22 | 100% | 0 | – | – |

The 2.0–4.0 row is the whole thesis in one line: accuracy cracks to 95%, the
only asks available are at **0.990**, and the three trades lost **−32%**. One
miss at 0.99 erases ~99 wins. That is the capital sink, reproduced live on our
own fleet — not just inferred from the target wallet.

**THE DECISION RULE: accuracy must exceed the entry price.** Applying it to the
timing sweep is decisive, because several high-availability cells are NEGATIVE:
| coin | entry | bars | acc | buyable% | med ask | EV/trade | EV/bar |
|---|---|---|---|---|---|---|---|
| eth | T−50 | 16 | 94% | **62%** | 0.950 | **−1.1%** | negative |
| bnb | T−40 | 16 | **100%** | 25% | 0.970 | +3.1% | +0.77% |
| **hype** | **T−40** | 19 | **100%** | 16% | **0.940** | **+6.4%** | **+1.02%** |
| sol | T−35 | 18 | 94% | 33% | 0.980 | **−4.1%** | negative |
| doge | T−30 | 16 | 100% | 0% | – | – | – |
| btc | T−25 | 16 | 94% | 12% | 0.970 | **−3.1%** | negative |
| xrp | T−20 | 17 | 100% | 12% | 0.980 | +2.0% | +0.24% |

**Chasing availability is a trap.** eth@T−50 has the most liquidity (62%) and
is EV-NEGATIVE, because 94% accuracy cannot pay for a 0.950 entry. The viable
cells are the 100%-accuracy ones, and among those **hype@T−40 has the cheapest
median (0.940)** → best EV/bar. The live bot is already parked there; this is
the first evidence that placement was right rather than lucky.

Reconciles with the target wallet: they win 87.6% on hype yet earn +10.5%/$
there — cheap entries tolerate lower accuracy. Same mechanism, our numbers.

## Session close-out (2026-08-15 ~02:25 Kyiv)
Fleet: **7/7 pods, 0 restarts**, paper bots 82min uptime, hype live 43min.
Balance **$93.58 unchanged** — no fills, no losses, caps never touched.
118 matched bars logged. Snipe skips flat at 18 (loop healthy, cheap tail just
absent — expected at ~3% of bars).

⚠️ **Local background tasks are being killed repeatedly in this session** —
monitors and timed accumulators do not survive. This does NOT affect the
cluster: every pod writes to its own PVC-backed
`/app/logs/logs-training-events.jsonl`, so data accrues regardless and
`scratchpad/vm_measure.sh` re-derives everything on demand. A future session
should poll in the foreground rather than rely on a persistent monitor.

## STATUS 2026-08-16 ~11:40 Kyiv — 6-coin live fleet, everybar experiment

Timeline since the doc above (details: docs/vacmaker-offline-notes.md §7-15,
current state: docs/README.md §2):
- 08-15 morning: sweep harvest → **eth tl50 + bnb tl40 flipped LIVE**
  (hype tl40 already live); coverage-gate bug found+fixed
  (pmTeMinCoverage; floor rule (62−tl)/59 − slack).
- 08-15 evening: first losses (hype tl40 2× on coverage-0.33 partial
  reads → gate 1.0 → user REMOVED hype tl40). Whale tape re-pulled (299
  trades 08-15): median fill 0.99, entries T−14→T+90, xrp 31/31 at 0.99 —
  our sol/xrp "failures" were a different cell (earlier entry + 0.98 cap).
  **Whale cells sol3/xrp3/hype3 deployed live** (tl14, cov 0.7, band ≤0.99)
  → renamed sol/xrp/hype (no version suffixes, user order); all paper pods
  removed, logs archived data/paper-sweep-final-20260815/. 43 dead configs
  deleted from chart/bots/. $5/order everywhere (LIVE_SIZE 9sh).
- 08-15 22:26: **EVERYBAR EXPERIMENT** (user): thresh 0.05bps, halt $999
  (off), revert snapshot chart/bots/revert-20260815-2225/. Result so far:
  ~80 fills, 97% win, wallet $93→$108 peak; the profit is the sub-0.90
  cheap entries (eth), the risk is whisper-entry (eth×3 losses, sub-0.5bps)
  + decay-to-tie (hype/bnb @0.9x, gate-immune). btc traded for the FIRST
  time ever under the 0.05 gate (17W/0L grind at 0.89-0.98).
- 08-16 08:21 UTC: **execution fix** (prewarm + retry-FAK, see TWAPEDGE.md
  §6) after the no-fill investigation: 11/11 kills were vanished asks
  (~450ms path, neg-risk REST in-line), all would-have-won, ≈$7-8 forgone.
  GTC-resting alternative REJECTED (backtesting.md ledger #16 —
  survivor bias; resters fill on flips). T−14 supply wall stands: ask>0.99
  blocks ~85% of whale-cell signal bars — continuous-entry window is the
  open build.
- Fleet cells: eth tl50 / bnb tl40 / btc tl25 (≤0.98) + sol/xrp/hype tl14
  (≤0.99, cov 0.7). Shared wallet 0xdb66d896 ~$105-108.
