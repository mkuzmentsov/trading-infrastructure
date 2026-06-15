"""Stress / scenario replay (§4.8).

Replay pathological tapes — flash crashes, exchange outages, funding spikes, stablecoin
de-pegs — and assert the system behaves *safely* (de-risks, halts, flattens), not
necessarily profitably. A strategy can lose money in a stress scenario; it may not
behave *dangerously* (runaway leverage, ignored stops, order storms).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Scenario:
    name: str
    description: str
    # A scenario is a tape transform: takes the base event stream, returns a perturbed one.


SCENARIOS = [
    Scenario("flash_crash", "instantaneous -30% wick and recovery"),
    Scenario("venue_outage", "data + order I/O frozen for N minutes, then resync"),
    Scenario("funding_spike", "funding rate 10x for several settlements"),
    Scenario("stable_depeg", "quote/collateral asset de-pegs"),
    Scenario("liquidity_drought", "spreads blow out, depth collapses"),
]


def run_scenario(engine_factory, scenario: Scenario) -> dict:
    """Run the engine over the perturbed tape; assert safety invariants held.

    Returns a pass/fail report per invariant (no leverage breach, stops honored,
    no order storm, kill switch reachable).
    """
    raise NotImplementedError("perturb tape per scenario; run engine; check safety invariants")
