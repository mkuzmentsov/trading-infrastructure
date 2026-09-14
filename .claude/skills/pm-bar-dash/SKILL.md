---
name: pm-bar-dash
description: Autopsy ONE Polymarket crypto up/down bar from the mrec tape and publish a two-chart dashboard (order book bid/ask + Chainlink/TWAP/Binance price) with our entries, the market open/close and the TWAP windows marked. Use when the user pastes a polymarket.com/event/<coin>-updown-<dur>-<ws> link or says "break down this market", "bar autopsy", "chart this bar", "what happened on that bar".
---

# pm-bar-dash

One bar, end to end: pull the tape → reconstruct the settlement → read what the bot did →
publish an interactive dashboard. Built 2026-09-14 on `doge-updown-5m-1789403700`.

The slug's trailing number is the **window START** (`ws`); the bar closes at `ws+300`.
`polymarket.com/event/doge-updown-5m-1789403700` = 16:35→16:40 UTC.

## Run it

```bash
cd <repo root> && source ./.dev-env-source          # MANDATORY — see gotcha 6
python3 .claude/skills/pm-bar-dash/build_dash.py <coin> <slug|ws> --outdir <scratch>
# …optionally edit <scratch>/dash.json: meta.entries[].note, meta.facts, meta.title_html
python3 .claude/skills/pm-bar-dash/assemble.py <scratch>/dash.json <scratch>/bar.html
```

Then publish `bar.html` with the **Artifact** tool (favicon 📉). `build_dash.py` already fills
every narrative slot with a sensible default, so a bare run renders a complete page — the notes
are where *your* analysis goes, and they take HTML.

Flags: `--no-pod` (skip the bot's event log), `--no-pull` (never kubectl-pull a missing hour).

## What it produces

* **Chart 1 — order book.** Best bid/ask for **one** token, spread shaded. Market prints (every
  taker trade on the market) as ink marks — ▲ bought this token, ▼ bought the other, **area ∝
  shares**. Open/close rules, hatched pre-open and post-close regions, our entries as labelled ink
  annotations in the top gutter.
  ⚠️ **Print density varies ~70×**: btc runs ~3,000 prints per bar, the alts ~45. The control is
  `Off / Big / All`, defaulting to **Big (≥ p90 shares)** whenever a bar has >300 prints — that is
  ~10% of the marks and ~60% of the volume. Flat-sized marks at full density bury the book lines
  entirely *and* misrepresent volume (btc's median print is 10 sh, its max is 10,000).
* **Chart 2 — settlement price.** Chainlink point price, venue TWAP feed, Binance spot mid on one
  axis; both 60-second averaging windows shaded; axis toggles to bps-vs-strike. The two levels
  that decide the bar — **OPEN (strike, dashed) and CLOSE (final, solid)** — are drawn across the
  plot with the value chipped onto the y-axis and the name in the right margin. On a near-tie they
  are a pixel apart, so the chips de-collide and draw a leader back to their true line.
* Linked crosshair, four zoom presets, entries table, full print tape, both themes.

## Gotchas — each of these cost real time

1. **⚠️⚠️ NEVER bucket Binance to 1 second.** These bars turn over in ~100 ms. On the reference
   bar, 1-second means read "+2.62 bps, reverted 2 s ago"; the raw tape reads **+7.86 bps until
   T−16.76 then +0.74 at T−14.02**. The freshness counterfactual *inverts* between the two
   (−0.198 vs −0.610). `build_dash.py` keeps the raw `bookTicker` inside T−45…T+75 for this reason.
2. **Anchor any book statistic on the FIRE row, not the neighbouring one.** The row whose ask
   equals the ledger's `seen_ask` is the decision row. One 10 Hz row earlier, the reference bar's
   `dB6` reads **+0.40** instead of **−0.42** — opposite verdicts from the same rule.
3. **`PF_TE_VERIFY` outranks our recon.** `recon.py` averages only the ticks the recorder received
   and lands ~0.03–0.5 bps off (reference bar: −0.602 vs the venue's −0.571). The script prefers
   `true_move_bps` whenever the pod log is reachable, and says which it used.
4. **`panel.est_bps` is NOT the live estimator (bug #45).** `core/rtds.py window_mean` forward-fills
   to `end−3` *unconditionally*; `panel.py` truncates at the relay frontier. Don't explain a fire
   with panel's number — reconstruct the live one from `cl.parquet` over the full 60-second window.
5. **The pod ledger does not charge the taker fee.** `fee = sh·0.07·px·(1−px)`. The script reports
   the ledger figure with the net in the sub-line; keep both.
6. **kubectl context trap.** A `source ./.dev-env-source` that fails silently leaves kubectl aimed
   at the dead EKS cluster and every `exec` hangs for the full timeout. Absolute-cd first.
7. **The raw hour may already be gone.** `archive_mrec.sh` converts `brec` → `pq-venue` and prunes
   the raw file. The script reads the parquet first and falls back to raw.
8. **The current hour is not rolled yet.** Recorders gzip on the hour; a bar from the current hour
   has no `.gz` to pull. Wait for the rollover.

## Design rules baked into the template — do not undo them

* **Plot ONE token.** `ua ≡ 1 − db` exactly, so drawing both tokens draws the same information
  twice, mirrored — that is what makes these charts unreadable. Trades in the other token are
  mapped to `1 − px`. The switcher flips which token is the subject.
* **Two hues only on the book chart**: ask blue `#2a78d6`, bid orange `#eb6834` (validated
  all-pairs, both modes). Entries are **ink** rules with a status chip beside the *label* —
  status red/green as a line colour FAILS CVD against the bid orange (ΔE 4.1). Prints are ink
  triangles: direction by shape, never by hue.
* Price chart uses a disjoint set — violet / amber / aqua — so a hue never means two things.
* Re-run `dataviz/scripts/validate_palette.js` before changing any of it.

## Related

Reference write-up: `winner-vacuum/docs/bar-autopsy-doge-20260914-1635.md`.
Bug ledger: `winner-vacuum/docs/backtesting.md` (#45). Pipeline: `winner-vacuum/tools/mrec/README.md`.
