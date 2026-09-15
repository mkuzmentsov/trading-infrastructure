> ⚠️ **One claim here is wrong**: `LIVE_INFLIGHT_CAP`'s *code* default is $120, but
> **`PM_TE_LIVE_INFLIGHT_USD=60` is set live on all 7 pods** — verified. The incident doc's $60
> leak arithmetic stands. The `LIVE_SIZE`-is-SHARES finding (twapedge.py:441) and the hard
> `sh>=5` / `sh*ask>=$1` floor at :442 are **confirmed** and are the load-bearing part.

# SIZE2.md — the survivable-size frontier, and the risk price of the two live levers

**2026-09-16. Read-only. Nothing deployed, nothing proposed for deployment.**
Author: portfolio/risk lane (round 2). Scripts: `research/s{1,2,3,4,5,6}*.py` → `research/out/size2/`.
Universe: `research/data/fills.parquet` — 4,390 settled live fills, 29 UTC days, 7 coins, +$242.79.
Model join: `data/evx.parquet` + `out/models/pwin_wf.pkl`, **100% matched** to 2,222 live fills over
the 20 OOS days (08-26→09-14), all 7 coins.

---

## 0 — Corrections to my own round-1 report

Three config claims in ALLOC.md §3/§4.3/§8 were **false**. Verified this round against
`winner-vacuum/chart/bots/*.yaml` and the live pods (namespace `every-tick-single` — I had looked in
a namespace that does not exist, which is why my `kubectl` returned nothing and I wrote "not set"):

| ALLOC.md claim | truth |
|---|---|
| "`pmTeFirstSkipLo/Hi` is not set in any values file, so §58 was never deployed" | set in **13** values files; **live** on 6 of 7 coins (`SKLO=0.90 SKHI=0.98`); eth deliberately exempt (`0/0`), exactly as the config comment says |
| "`pmTeRiskPersist` appears in no values file; halt state is wiped on restart" | set in **14** values files; **`PM_TE_RISK_PERSIST=1` live on all 7 pods**, `/app/logs/risk-state.json` present and being written on all 7 |
| §8 Proposal H1 item 1 ("set `pmTeRiskPersist: 1`") | **already true.** Withdrawn. |

Two consequences beyond the retraction:

1. **§4.3 "Defect 2" is dead**, and with it the stated cause of doge's 4 post-trip order leaks. That
   replay needs re-running against a persisted counter; I have not re-run it. H1 item 2 (re-express
   the daily-loss limit as a multiple of one bar's exposure) is untouched by this and still stands.
2. **§3's "mystery" is solved and is not a mystery.** I reported that fleet exposure to the mid-band
   collapsed 6.7× in ERA2 and could not say why. It is the first-clip skip gate, live on 6 coins from
   08-30 — one day before ERA2 starts. The lane did not decay; **we turned it off.** That strengthens
   §3's conclusion (killing a lane the fleet has already stopped using buys ~$0) and removes the
   suggestion that some unknown regime change did it.

I also over-reported one alignment failure this round before catching it: my first join of the ml
lane's predictions read "bnb and btc have no model rows". That was **my** bug — I failed to sort by
`ws` before the positional assignment that `ev9_size.py` does. The ml lane's alignment is correct;
all 7 coins have predictions. Nothing in MODELS.md is affected.

---

## THE DECISION

**Cut the book to k≈0.5 — and run it as an information purchase, not as an income stream.**

Round 1 asked "should we size up" and answered *hold*. That answer does not survive being asked the
other way. The asymmetry is this:

* **The cost of de-sizing is undetectable.** k=1 → k=0.5 gives up $4.68/day. Detecting $4/day against
  a day sd of $35.93 takes ~633 days. We cannot ever know we paid it.
* **The benefit of de-sizing is arithmetic.** Zero-edge P(equity<$50) over the window needed to learn
  whether the edge exists falls **31.5% → 14.0%**. That is not an estimate with a confidence interval;
  it is a property of the bet size and the observed daily distribution.

Per my own standing rule — *when a change moves $/day below the noise floor, decide it on mechanism* —
the mechanism here is unambiguous and points one way.

**Bankroll assumed: $450.** Unchanged.

---

## 1 — TASK 1: the survivable-size frontier

### 1.1 The constraint that defines the frontier, and that nobody had costed

`winner-vacuum/chart/files/scripts/twapedge.py:442`

```python
sh = float(int(min(LIVE_SIZE, LIVE_MAX_ORDER_USD / max(ask, 0.01))))
if sh < 5 or sh * ask < 1.05:     # venue minimums: 5 shares AND $1
```

Clips are **integer shares with a hard floor of 5**. `LIVE_SIZE` is 8 *shares*, not $8 — the median
request in the ledger is exactly 8 shares (≈$7.9 at a favourite price), the ladder is 24.

**Therefore k=0.5 and k=0.25 as the brief states them do not exist.** 8 × 0.5 = 4 shares is rejected
by the venue. Applied naively, "halve the book" does not halve anything — it **deletes 60% of fills**
(every base clip) and keeps the $24 ladder clips, i.e. it *raises* per-clip concentration:

| naive k | rows killed by the venue minimum | mean surviving clip | top-1 share of net |
|---|---|---|---|
| k=1 | 0% | 13.3 sh | 31% |
| k=0.50 naive | **60.0%** | 10.9 sh | 40% |
| k=0.25 naive | **68.1%** | 6.0 sh | 44% |

The executable form of "run smaller" is `sh = max(5, int(k·req_sh))` — the floor **clamps**. Every
number below uses that.

### 1.2 The frontier

Rescaling is exact, not modelled: `net_i = sh_i·[(won_i − px_i) − 0.07·px_i(1−px_i)]` is **linear in
shares at fixed price**, so a fill's net scales with its share count. Depth is taken from the ledger
itself — where completion < 1 the book gave us everything it had at our limit, so `avail_i = filled_i`
is *observed*, not assumed; where completion = 1 we only learn `avail_i ≥ req_sh_i` and never
extrapolate above it (k ≤ 1 throughout). The k=1 row reproduces the live ledger to the cent.

| size | stake/day | $/day | day sd | t | **days to detect** | **P(<$50) at zero edge, over its own horizon** | P(<$150) same | median maxDD | p95 maxDD | median maxDD if edge real |
|---|---|---|---|---|---|---|---|---|---|---|
| **k=1.00 (live)** | $2,218 | **+8.37** | 35.9 | 1.25 | **144** | **31.5%** | 44.5% | $439 | $887 | $191 |
| k=0.75 | $1,724 | +5.81 | 27.0 | 1.16 | 169 | 22.1% | 35.3% | $359 | $725 | $158 |
| k=0.625 (uniform floor) | $1,466 | +4.71 | 22.9 | 1.11 | 185 | 17.3% | 30.1% | $322 | $648 | $143 |
| **k=0.50 clamped** | $1,324 | **+3.69** | 19.4 | 1.02 | **217** | **14.0%** | 26.5% | $297 | $597 | $134 |
| k=0.25 clamped | $1,041 | +2.15 | 12.4 | 0.93 | 260 | **3.6%** | 11.7% | $212 | $422 | $97 |

Day-block bootstrap of the **empirical** 29-day net series, 60k paths, absorbing barrier, never
Gaussian. The k=1 zero-edge figure (31.5%) independently reproduces ALLOC.md's 31.8%.

**P(<$150) is the number I would actually watch.** Peak concurrent fleet exposure is $142; below
$150 the book cannot fund its own working capital and de-sizes involuntarily. At current size that
is a **44.5%** chance under the null — close to a coin flip.

### 1.3 The answer to the question the brief actually asked

**No — detection time is not invariant to size, and I can say exactly why.**

Under pure proportional scaling it would be: mean and sd both scale by k, so t and therefore
days-to-detect are invariant, and size would be a free risk dial. That is the correct intuition and
**the 5-share floor is what breaks it.** The floor clamps the base clip (8 → 5 shares, −37%) while the
ladder scales freely (24 → 12, −50%), so de-sizing changes the *mix* as well as the scale. The mean
falls faster than the sd, and n80 ∝ roughly k^−0.4:

| | k=1 → k=0.5 clamped |
|---|---|
| $/day | ×0.44 |
| day sd | ×0.54 |
| days to detect | 144 → 217 (**+51%**) |
| zero-edge P(ruin) over that horizon | 31.5% → **14.0%** (**÷2.2**) |

So the trade is real but strongly favourable: **you buy a 2.2× reduction in the chance of losing the
account before you learn anything, for 50% more calendar time.** I would take that trade at these
odds. It is not free, and I am not going to claim it is.

Two mechanisms I checked and am *not* crediting:
* **Halts.** Smaller clips trip the fixed-dollar daily stops less often, which would return bars. But
  §2.1 of ALLOC (coin PnL does not persist between halves; split-half Spearman −0.50) says we have no
  basis for signing those bars. Counted, not credited.
* **`LIVE_INFLIGHT_CAP`.** Default $120/pod (`twapedge.py:69`, env unset on all 7). Smaller clips
  would delay the ratchet described in commit e1f9e86 — but that is a **defect to fix**, and delaying
  a bug is not a sizing argument. Excluded.

### 1.4 Is it worth running at all?

**As an income stream: no, at any size.** At full size the median one-year path draws down $191 on a
$450 account *if the edge is exactly as measured*, and the edge cannot be distinguished from zero.
$3.69/day at k=0.5 will not pay for the hourly babysitting, 7 pods and standing research load. Anyone
optimising this book for income is optimising the wrong objective.

**As an information purchase: yes, and only at reduced size.** The single asset this program owns is
a 29-day ledger with t=1.25 and a plausible mechanism. The only thing that converts it into knowledge
is more days. De-sizing is the cheapest available way to raise P(we are still here at day 217) —
and the fee saving is genuinely proportional, because the fee is linear in shares.

I will say the harder half plainly: **if the fleet is still at t < 1.5 after another 60 days, the
honest read is that $8.37/day was 29 days of luck**, and no sizing rule rescues that. Round 1 said
the book returns 1.86%/day on $450 if real. It should not be defended indefinitely on a t of 1.25.

### 1.5 Era split (bug #24, applied to my own new result)

Every row of the frontier is an ERA2 phenomenon. ERA1 is flat-to-negative at every size:

| size | ERA1 (14d) | ERA2 (15d) |
|---|---|---|
| k=1.00 | −0.64/day (t −0.11) | +16.79/day (t +1.46) |
| k=0.625 | −0.06/day (t −0.02) | +10.38/day (t +1.38) |
| k=0.25 clamped | −1.36/day (t −1.68) | +4.09/day (t +1.28) |

**The ordering of the frontier is stable across eras even though the level is not** — smaller is
smaller in both halves, which is the only property the sizing decision depends on. But note the
level: the entire +$242.79 is ERA2. This is a 15-day result wearing a 29-day label.

One genuinely era-stable object turned up: capping every clip at 5 shares (no ladder at all,
$994/day staked) is the only scheme **positive in both halves** (+1.03 and +2.84 $/day). Its $/day is
far below the noise floor and I am not proposing it — but it is the only configuration whose sign did
not flip, and it is worth a line in anyone's notes.

---

## 2 — TASK 2: the τ=0 veto is an artefact of the eval universe, and does not transfer

**Verdict: the capacity result is not real. It is also the most valuable thing to chase.**

### 2.1 What it would be worth if it were real

Priced on the live ledger (best-case model, est-block/hgb), a costless 65%-drop veto buys:

| | flat | τ=0 veto | |
|---|---|---|---|
| stake/day | $1,968 | **$690** | −65% turnover |
| $/day | +9.38 | +9.33 | −0.05, nothing |
| day sd | 41.23 | **30.84** | **−25%** |
| **days to detect** | 151 | **85** | **−44%** |
| **P(<$50) at zero edge, own horizon** | 38.9% | **13.5%** | **÷2.9** |
| median maxDD (zero edge) | $514 | $286 | |
| fee paid | $4.14/day | $1.87/day | (already inside the $/day above — not additive) |

That is a bigger prize than any PnL lever anyone has produced this round. It is exactly the right
shape: it improves the risk side without needing the edge to be real.

### 2.2 Why I do not believe it

I first reconciled against the ml lane's own universe and matched it exactly — τ=0 drops **40.3–47.9%
of fired evals** across the 6 models, against MODELS.md's "40–48%". The join is sound.

Then I applied the same bar-level decision to the **live clip population**, which is what actually
trades. The bot fires several clips per qualifying bar, and the vetoed bars are disproportionately the
multi-clip ones:

| model (all 6, equally calibrated) | drops, live | $/day | **paired Δ vs flat** |
|---|---|---|---|
| margin-only/logit | 63.5% | +3.97 | **−5.41** |
| margin-only/hgb | 62.5% | +3.66 | **−5.72** |
| est-block/logit | 65.2% | +6.31 | **−3.07** |
| est-block/hgb | 64.5% | +9.33 | −0.05 |
| est-block/hgb_s | 65.8% | +10.16 | +0.78 |
| full(+ask)/hgb | 76.3% | +0.80 | **−8.58** |

* **The same rule drops 62–76% of the live book, not 40–48%.**
* **Spread across six equally-calibrated models: −$8.58 to +$0.78/day — a range of $9.35, versus the
  $0.69 range the eval universe showed. 13× wider.** Four of six are materially negative.
* The best cell (est-block/hgb, −$0.05/day) does not survive its own attacks: LOO-day paired delta
  **[−3.81, +4.60]**, **10/20 days improved** — a coin flip. Per coin: bnb −6.35, btc −2.43, sol −1.79
  against doge +4.60, hype +3.13. Era: **+3.73 in ERA1, −1.31 in ERA2 — the sign flips**, bug #24 again.

The mechanism of the failure is legible and is this venue's recurring one: the veto scores a bar at
its **displayed ask**, while the money is made by clips that fill *below* that ask. Deciding on the
displayed number and being paid on the filled one is the same error as §72's ghost quotes and bug #33.

**So "the same money from roughly half the trades" is true in the eval universe and false in the
book.** I cannot hand back a capacity gain. What I can hand back is the size of the prize (§2.1) and
the reason it is the right thing to keep attacking: a *costless* 60%-turnover cut is worth more to
this program than any $/day lever on the table, because it acts on the denominator of every ruin
number rather than on an edge we cannot prove.

---

## 3 — TASK 3: cap2x buys return with variance, and is not budget-neutral in execution

**Verdict: reject on risk grounds, independently of whether the edge is real.**

### 3.1 It moves ruin materially and detection not at all

Live ledger, 20 OOS days, `w = clip(1+20·(p̂ − ask − fee), 0.5, 2.0)` renormalised per day, under the
ml lane's own best-case assumption that the extra size fills:

| | flat | cap2x (p_full) |
|---|---|---|
| $/day | +9.38 | +13.20 |
| day sd | 41.23 | **56.54 (+37%)** |
| **t** | 1.02 | **1.04** |
| worst day | −$74.56 | **−$92.95** |
| max single clip | $57.45 | **$118.86 = 26% of bankroll** |
| **P(<$50) at zero edge, 144d** | 38.2% | **51.1%** |
| median maxDD (zero edge) | $501 | $695 |
| P(<$50) if edge real | 0.5% | 2.6% |

**t is unchanged. The entire extra return is bought with variance** — which is the definition of a
rule that is not improving the book, only levering it. And it adds **13 points of zero-edge ruin**.
Applying the veto and cap2x together is worse than either: P(<$50) reaches **23.9% even under the
measured edge**.

The brief asked whether a rule adding $2.72/day while moving P(ruin) materially is an improvement.
On these numbers it is not, and the $2.72 is the smallest version of it — priced on the live clip
population the same rule reads +$3.8 (p_full) to +$11.0 (p_est)/day, which should increase the
suspicion rather than the enthusiasm.

### 3.2 It is budget-neutral only in intent

This is the part no one else could see, because it needs the venue floor and the ledger's own
completion ratios together:

| | p_full | p_est |
|---|---|---|
| intended stake (renormalised) | 99.4% of flat | 99.3% of flat |
| **executable stake** | **93.9%** | **92.3%** |
| down-weighted clips | 58.9% | 61.8% |
| **…of those, below the 5-share venue minimum — the cut cannot be made** | **17.4%** | **22.5%** |
| up-weighted clips | 41.1% | 38.2% |
| **…of those, PROVEN unfillable by this ledger's own completion ratios** | **18.9%** | **19.3%** |

Both halves of the rule are partly unexecutable, in opposite directions. `w=0.5` on an 8-share clip
is 4 shares — **rejected by the venue**, so the risk reduction the rule promises on its worst bars
simply does not happen. Meanwhile ~19% of the up-weight is not available.

That last figure **partially resolves what MODELS.md called unresolvable.** The ml lane wrote that
settling the fill assumption "requires observing fills at more than one clip size, which no existing
tape contains". It does not: wherever a live clip completed at less than 100%, the book **told us its
ceiling at our limit price** — that is a measurement, not a display. On 19% of up-weighted rows the
extra shares are provably unavailable. It is a lower bound (rows that completed fully have an unknown
ceiling), and it is one-sided in the damaging direction. The honest reading of the fill question is
therefore **worse than "unresolved"**: the part we can observe already fails.

### 3.3 Halt interaction

ALLOC §4.2 measured `lives_per_episode` (daily-loss limit ÷ largest single-bar stake) at 0.63 on the
$30 coins — the first loss of any size already trips the stop. cap2x roughly halves it again:

| coin | limit | flat | cap2x |
|---|---|---|---|
| btc | $30 | 0.63 | **0.35** |
| hype | $30 | 0.52 | **0.25** |
| doge | $7 | 0.15 | **0.11** |

A rule that doubles the largest clip while the daily-loss stop stays fixed in dollars is a
**behavioural change to the halt layer** that is nowhere in its own proposal. Per the standing rule,
unknown means delay.

---

## 4 — What I would put forward, and what would reverse it

**Not a deploy proposal.** The user decides.

### Proposal S1 — reduce clip size to k≈0.5, clamped

`LIVE_SIZE` 8 → 5 shares (the venue floor) and `pmTeWhaleLadderUsd` 48 → 24 / `liveMaxOrderUsd`
24 → 12, i.e. `sh = max(5, int(0.5·req_sh))`. Fleet-wide or not at all — a per-coin subset
reintroduces the selection problem §2.1 rules out.

* **What it assumes:** bankroll $450; nothing about the edge being real. That is the point.
* **Revert path:** restore `liveMaxOrderUsd`, `pmTeWhaleLadderUsd` and `LIVE_SIZE` to the literal
  per-coin values in ALLOC §1.4. Single-key helm revert per coin, no code change. **Do not
  fleet-restart to apply it** — that is the 08-22 failure in memory; stage it per coin at a UTC day
  boundary so the halt counters and the A/B stay legible.
* **Judging metric — explicitly NOT PnL** (PnL cannot judge this; the difference is 633 days from
  detectable):
  1. **Realised stake/day**, target $1,324 ±10%. Countable in 2 days. This is the only thing the
     change is *for*.
  2. **Per-coin completion ratio at ask ≥ 0.98** — a falsifiable mechanism prediction, not a
     restatement. Smaller requests should complete closer to 1.0 on the thin coins: hype 0.824 and
     bnb 0.906 should move above ~0.95 within 3 days. **If they do not, my depth model is wrong and
     the frontier's $/day column is wrong with it** — that would be the finding, and it would be
     worth more than the size change.
  3. **Max single-bar stake**, target ≤ $29 (from $57.45). Countable immediately.
* **Behavioural warning:** this changes which bars fill and how often the fixed-dollar halts trip
  (doge's $7 limit becomes ~0.3 lives instead of 0.15). It is a behavioural change, not a neutral one.
* **Sequencing:** the eth/xrp/hype de-selection (ALLOC §2.2, now plausibly commit e1f9e86's inflight
  ratchet, `LIVE_INFLIGHT_CAP` default $120) should be **fixed first**. Three of seven coins are
  currently out of the book by accident; measuring a deliberate size change on top of an
  unreconciled accidental one wastes the experiment.

### Reject

* **cap2x sizing** — §3. +13 points of zero-edge ruin, no change in t, not executable as specified.
* **τ=0 veto as a capacity lever** — §2. Does not transfer; sign depends on which of six equally
  calibrated models you pick.
* **Any size increase** — unchanged from round 1 and now with a second reason: at k=1 we are already
  at 44.5% probability of falling below fundable working capital under the null.

### What reverses each call

| call | what reverses it |
|---|---|
| **cut to k≈0.5** | Completion ratios on the thin coins **not** rising when requests shrink (judging metric 2) — that would mean fills are not depth-rationed and the frontier's $/day column understates the cost of de-sizing. Or the fleet clearing t ≈ 2 on its own record, which makes the edge real and the ruin branch irrelevant. |
| **reject cap2x** | A tape that observes fills at two clip sizes on the same bar. The randomised size arm from ALLOC §7 (alternate clip size per bar by hash of bar id) produces exactly that, settles §3.2's fill question directly, and would also settle round 1's $8-vs-$24 question in ~40 days. **It remains the single highest-value experiment I can name, and it is now the prerequisite for two separate proposals.** |
| **reject the veto** | The same τ=0 rule scored on the live clip population, not the eval universe, coming out non-negative across **all six** models rather than two. That is a re-scoring, not new data — it can be done today. |
| **run the book at all** | 60 more days at t < 1.5. |

---

## 5 — What I could not resolve

* Whether the doge post-trip order leaks in ALLOC §4.1 are real. That replay assumed halt state was
  wiped on restart; it is not. **Needs re-running against the persisted counter**, and
  `PF_TE_LIVE_HALT` events still were not in the pulled ledger.
* Whether the `LIVE_INFLIGHT_CAP` ratchet (commit e1f9e86) is what de-selected eth/xrp/hype. It fits
  — cap $120/pod, peak fleet exposure $142 — but I am read-only on pods and did not confirm it.
* The frontier's $/day column above k's own data: I never extrapolate fills above observed
  availability, so **k > 1 is not costed anywhere in this document** and should not be inferred from it.
