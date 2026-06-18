# Roadmap

Where this can go next, grounded in what's built and what the work actually surfaced.
The original phased plan lives in `INITIAL_REQUIREMENTS.md` §9; this is the living
version — updated as of the meta-label / xsec / stress / paper / live-adapter slices.

## Done (working, tested end-to-end on real data)

- **Data** — ccxt ingest, interval-aware point-in-time Parquet store, content-addressed snapshots.
- **Engine** — one event-driven decision path shared by backtest, paper, and live (NFR1).
- **Backtest** — realistic friction (fees + size-aware slippage), full metric suite, run provenance.
- **Validation harness** — purged/embargoed CV, **CPCV + PBO**, Deflated Sharpe, leak-checks, approve-for-live gate.
- **Strategies tested** — Tier-1 trend baseline, meta-label GBT (triple-barrier, purged CV, economic test), cross-sectional momentum panel.
- **Risk** — vol-targeting, drawdown breaker, leverage clamp, kill switch; stress/scenario replay proving the breaker fires.
- **Deployment** — paper runner (replay/live feed), persistence + safe restart, JSONL audit log, Docker/compose.
- **Live execution** — real order I/O via one ccxt broker (Kraken/HL), env-only credentials, guarded behind the gate.

**Standing finding:** three strategy families, all rejected OOS after costs (PBO 0.73–0.77).
No edge has cleared the gate. The harness is the deliverable.

---

## Near-term — close the loops already started (small, high-value)

1. **Regime classifier (§2.4).** `TrendRangeDetector` is a passthrough returning `UNKNOWN`.
   Implement a real ADX / efficiency-ratio / vol-percentile / Hurst classifier so the
   regime gate can actually turn strategies on/off, and add the **per-regime metric
   breakdown** (§3.3, §4.7) to every report. Makes the gate meaningful and exposes
   one-regime-wonders.
2. **Wire stops into the engine loop (§2.5).** `risk/stops.py` exists but `RiskGate` is
   built with `stops=None`. Map triple-barrier exits to live net-exposure stops and run
   them inside the loop, so the stop-honoured stress check graduates from NOT-APPLICABLE.
3. **DSR + PBO on the meta-label economic test.** The metalabel command reports OOS AUC +
   an OOS backtest; fold in Deflated Sharpe and a PBO over the model's hyperparameter grid
   so the ML path is judged by the same gate as the rules.
4. **Walk-forward retraining harness (§4.5).** `validation/walk_forward.py` is a stub;
   implement rolling fit→trade→refit using the existing `CombinatorialPurgedCV`. This is
   the most production-faithful backtest and the one that exposes edge decay.
5. **Funding settlement in PnL (§3.2).** Backtest `FillSimulator.apply_funding` and the
   live broker both need funding charged at settlement for perps — currently flagged, not
   modelled. Requires the funding/OI ingestion below.

## Edge hunting — the actual research (where profit, if any, lives)

The methodology says single-asset directional ML rarely works; spread the search.

6. **Vol-managed / momentum-crash protection.** Xsec momentum showed skew −3.47 (the
   §6.2/§12 account-killer). Add a volatility-scaling overlay (Barroso–Santa-Clara) and a
   crash filter; re-test whether risk-managed momentum survives OOS where raw momentum didn't.
7. **Position-horizon trend (1d/1w, trailing stops).** The place trend-following
   historically survives. Test long-lookback time-series momentum with proper trailing
   stops on the position horizon, judged by PBO not a single split.
8. **Richer, leakage-safe features.** Wire the existing `fracdiff.py` into the live feature
   pipeline; add cross-asset/dominance, funding/OI context, and term-structure features.
   Re-run the meta-label with MDA to see if any feature family carries real OOS signal.
9. **Carry/basis as a *feature*, not a strategy.** Funding is a strong conditioner even if
   carry itself is out of scope here; use it to gate or size directional bets.

## Arbitration & multi-strategy (turn strategies into one book, §7)

10. **Graduate xsec into the event engine.** It currently runs only as a vectorized panel.
    Make it emit per-symbol forecasts (`CrossSectionalMomentum.forecasts`) so the combiner
    nets it with trend into one target book — the Carver design the architecture promises.
11. **Multi-symbol live engine.** The event loop processes one symbol per event; the
    universe path (cross-sectional ranking at each rebalance) needs the engine to hold a
    universe snapshot. Required before any multi-asset strategy goes live.
12. **Forecast weighting from validated edge.** The combiner weights are hand-set to 1.0;
    derive them from each strategy's validated edge × live confidence × risk budget (§7.2).

## Productionization & ops hardening

13. **Model registry + champion-challenger (FR10).** `model/registry.py` is a stub.
    Version every approved model with its data snapshot + commit + config + gate evidence;
    run challengers in shadow; promote only on an OOS win under the gate.
14. **Live drift auto-disable (§2.7, FR9).** `DriftMonitor` exists; wire it into the live
    loop to zero a model's weight when realized stats diverge from the approved baseline,
    *before* the drawdown breaker has to.
15. **Gate-pass artifact workflow.** Make `validate`/`metalabel` emit a signed
    `{name}_gate_pass.json` when a strategy clears, which `live` checks. Closes the
    paper→approve→live promotion path end to end.
16. **Monitoring surface.** Heartbeat/deadman in the live loop; NAV/exposure/PnL metrics
    export (Prometheus) + alerting; a small dashboard over the JSONL audit log.
17. **Async fill reconciliation.** Live fills are polled each bar (fine for swing/position).
    For tighter loops, reconcile partials/rejects/disconnects against venue state on every
    tick, not just restart.
18b. **Per-venue instrument constraints.** The risk layer clamps leverage but not
    *direction*: on a spot venue (Kraken) the engine can still produce a short target,
    which a real spot venue would reject. Add a per-venue constraint (long/flat only for
    spot, leverage cap per instrument) enforced in the risk gate / OMS before any order.

## Data & infrastructure

18. **Funding/OI ingestion.** `PointInTimeStore.append_funding` is a stub; ingest funding
    and open interest as point-in-time context series (needed for items 5, 9).
19. **Scale storage.** Parquet+pandas is fine now; move to DuckDB/ClickHouse when the
    universe and history grow (the store API already anticipates it).
20. **More venues / instruments.** WhiteBIT, more alts, and (only if a scalping edge is
    ever justified) L2 order-book ingestion — explicitly out of scope until then (§6.0).

## Longer-term / ambitious

21. **CPCV-driven backtest *distribution*.** Report the full distribution of OOS paths and
    the deflated-Sharpe-adjusted expectation, not just one number, for every candidate.
22. **Nautilus migration (§3.1).** Re-evaluate `nautilus_trader` for the live path once an
    edge justifies the dependency; the engine boundary was kept thin to allow this.
23. **Execution research.** Maker/limit placement, slippage/impact modelling from real
    fills, and TWAP/POV for larger size — only once there is size to execute.

---

## Guiding constraints (unchanged)

- Nothing ships that can't beat a dumb baseline **OOS, after costs** (principle #4).
- Every result carries an overfitting-risk number (PBO/DSR) and run provenance.
- Backtest == live: one decision path, always (NFR1).
- Risk has absolute precedence; the `live` guard stays shut until the gate is cleared.
