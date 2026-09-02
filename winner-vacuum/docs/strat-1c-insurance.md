# "Buy the 1c side when we hold the 99c favourite" (reversal insurance) — DEAD on our own tape, 2026-09-02

User thesis (09-02): *"vacmaker keeps losing 99c bets on eth, xrp and other
coins, there are many reversals, so buying at 1c in expectation of a reversal
should work."* Tested adversarially (optimist steelman + pessimist base-rate
verification) on **our own live trade tape**, not on ambient bars — the
conditioning §27/§42 never did. Artifacts: `scratchpad/rev1c/`
(`rev1c_VERDICT.md`, `rev1c_tape.csv` = 3,262 settled clips, sim scripts).

## The loss book (7 coins, 08-16 → 09-02, 1,900 bars with live fills)
**1,816W / 84L = 95.58% win, net +$87.00.** Gross wins +$1,126.68 vs gross
losses −$1,039.67 ⇒ **losses eat 92.3% of gross wins**. Per-coin net:
btc +105.81 · **eth +39.97** · doge +16.05 · sol +6.61 · hype −12.39 ·
bnb −17.45 · **xrp −51.61**.

## ⚠️ Two premises of the request are factually wrong
1. **"We keep losing on eth"** — eth is our **second-best** coin (+$39.97).
   The actual bleeder is **xrp (−$51.61)**.
2. **"We keep losing 99c bets"** — only **7 of 84 losses** (10.3% of dollars
   lost) came from entries ≥0.985. **77% of the money lost comes from
   entries below 0.96**; the 0.90-0.96 band alone is 37.7%.

## The decisive arithmetic (insurance on every bar we actually fired)
| variant | net |
|---|---|
| FANTASY — 1c on every fired bar (flip 4.42% vs 1.07% BE) | **+$1,077** |
| **ATTAINABLE — opposite ask = (1−p) + 1 tick** | **−$338** (5/18 days +) |
| zero-spread fantasy — opposite at exactly (1−p) | −$7 |
| dear bars only (≥0.985) at a real 2c | −$137 (1/18 days +) |
| dear bars only at an optimistic 1c | −$12.80 (ex-best-3-days −$68) |

Flip rate vs breakeven by entry band — **the 95% CI upper bound is below
breakeven in EVERY band**:

| entry px | bars | flip% [95% CI] | BE @ real opposite ask | verdict |
|---|---|---|---|---|
| ≥0.985 | 778 | 0.90 [0.24, 1.56] | 2.18% | DEAD |
| 0.96-0.985 | 621 | 1.61 [0.62, 2.60] | 3.64% | DEAD |
| 0.90-0.96 | 308 | 9.09 [5.88, 12.30] | 7.61% | point-estimate passes, **sim −$338** |
| 0.75-0.90 | 156 | 14.10 [8.64, 19.56] | 17.41% | DEAD |

**The trap in one line:** the 1c price only exists on bars that almost never
flip (0.90%); bars that flip often (14-42%) charge 15-32c for the same
insurance. The zero-spread run (−$7 on $1,417 of cost) proves the pair is
**fair to within 0.5%** — so every cent of spread is pure loss.

## Takeability (v2 depth ladders, favourite 0.97-0.99, n=15,922 observations)
Median opposite ask: btc 0.02 · eth 0.04 · sol 0.06 · xrp 0.07 · bnb 0.08 ·
doge 0.11 · hype 0.14 (fleet 0.08 ⇒ BE flip 8.52% vs observed 0.90%).
A ≤2c opposite ask with ≥5sh exists in only **10.3%** of dear observations
(btc 54.1%, eth 16.5%, xrp 7.5%, doge 0.5%, hype 0.0%) — and bug #23 says a
displayed 1c ask is often a phantom anyway. ⚠️ Only 40-50 fired bars overlap
the 12h v2 window, so per-fired-bar takeability is thin; the ambient pricing
measurement is not.

## Hedge framing (§27 re-confirmed on current data)
Pair cost 0.99 + 0.08 = **1.07** fleet-wide (1.01 btc best case) for a $1.00
payout ⇒ hedging is a guaranteed **−7.0% / −1.0%**. The pair always costs
more than it pays; there is no free insurance leg.

## Why the intuition misfires (worth keeping)
1,816 quiet wins of **+$0.62** vs 84 losses of **−$12.38** — a **20:1 payoff
ratio**. Each loss erases ~20 wins, so a 95.6%-correct book *feels* like it
is bleeding even while it nets positive. The felt pattern is real; the trade
it suggests is not. (Same asymmetry recorded in §37: "win count is useless".)

## Optimist steelman (independent fork, live-only join) — same verdict, and the MECHANISM

Join used: `PF_TE_WHALE_ORDER ⋈ PF_TE_LIVE_SETTLE` = 1,900 live-settled bars.
⚠️ **Accounting note:** this live-only join nets **−$34.14** where the
pessimist's all-settles join nets **+$87.00**. The two count different
things (live clips only vs every settled clip incl. ladder legs, and
slightly different windows). Neither is the wallet; per standing rule the
WALLET is truth. The *shape* of both is identical, and the shape is what
the verdict rests on.

Flip rate and PnL by entry band (live-only join):

| entry band | bars | flips | flip% | PnL |
|---|---|---|---|---|
| <0.75 | 33 | 15 | 45.5% | −$6.33 |
| 0.75-0.90 | 81 | 14 | 17.3% | +$3.18 |
| 0.90-0.95 | 137 | 12 | 8.76% | **−$54.56** |
| 0.95-0.98 | 393 | 16 | 4.07% | **−$32.35** |
| **≥0.98** | **1256** | **10** | **0.80%** | **+$55.91** |

⭐ **THE MECHANISM (new, and it closes the question):** on 128,596 sane
two-sided v2 snaps, `ua ≡ 1−db` in **100.0%** — the pair is one book. So the
dog's price is the favourite's bid, and on tight books (pair sum ≤1.10):

| fav ask | dog p10 | dog median | dog breakeven flip |
|---|---|---|---|
| 0.97 | 0.04 | 0.06 | 6.0% |
| 0.98 | 0.03 | 0.06 | 6.0% |
| 0.99 | 0.02 | 0.05 | 5.0% |
| ≥0.999 | 0.009 | **0.01** | 1.0% |

**The dog reaches 1c only when the favourite is at 0.999** — the most-locked
state, i.e. minimum flip probability. Per coin at fav 0.98/0.99 the dog
median is xrp 0.06/0.04 and eth 0.04/0.02, and **0.0% of xrp and eth
observations ever showed the dog at 0.01**. The two coins the thesis names
never offer the price the thesis needs.

EV of pairing every real fill with a dog buy at MEASURED prices:

| cell | n | flip% | dog cost | payout | EV |
|---|---|---|---|---|---|
| all ≥0.98 | 1256 | 0.80% | $629.81 | $103.00 | **−$526.81 (−83.6%)** |
| xrp ≥0.98 | 194 | 2.06% | $82.70 | $45.00 | −$37.70 (−45.6%) |
| eth ≥0.98 | 181 | 1.10% | $45.84 | $29.00 | −$16.84 (−36.7%) |
| every fill | 1900 | 3.53% | $1,345.38 | $727.00 | −$618.38 (−46.0%) |

Fantasy control (dog forced to 0.01): xrp +138%, eth +53% — but pooled still
−18.4%, and that price is counterfactual on exactly those coins. xrp's cell
isn't even significant: P(≥4 flips | 1% true, n=194) = 0.13 one-sided,
before 7-coin multiple comparison. Insurance on the ≥0.98 book: +$55.91 →
+$32.75 at a fantasy 0.01, −$93.41 at 0.02, **−$471.89 at the real 0.05**.

**It fails on PRICE, not on flip frequency** — our conditional flip rate at
≥0.98 (0.80%) would beat a true 1c dog. But the market moves the dog to
4-6c precisely when a flip is plausible and collapses it to 1c only when the
bar is locked. §27's "flip-prone bars are never priced at 1c", now with the
identity as the visible mechanism.

## What this DOES point at (the real lever, not the 1c side)
⭐ **Both forks independently reached the same lever**: the loss dollars sit
in the **mid-band entries (0.90-0.98)**, not in the dear lane. Pessimist:
77% of lost dollars come from entries <0.96, and xrp is the bleeder
(−$51.61). Optimist: bands 0.90-0.98 = **−$86.91 combined** vs **+$55.91**
for ≥0.98, i.e. the live-only book would have been roughly **+$90 over these
18 days with MIN_ASK at 0.98** instead of 0.55.

⚠️ This is a LIVE-PARAMETER question on a running bot (`pmTeMinAsk`), and it
contradicts the standing §38/§45/§47 decision to keep MIN_ASK=0.55 — which
was made on *offline path replays*, where the 0.55-0.90 band scored as the
profit centre ([strat-dipbuy](strat-dipbuy.md)). The new evidence is our own
LIVE fills over 18 days, a different and arguably better instrument. Before
any change: (1) re-run this split per-day and per-coin for episode
dependence, (2) reconcile against the WALLET, (3) note the regime caveat
(§51: chop days decayed the shallow-window edge — the mid-band bleed may be
regime, not structure). **No change made — operator decision.**
