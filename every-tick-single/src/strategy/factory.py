"""Strategy factory — maker_rebate is the only strategy in this project.
(The taker-era strategies live in git history / the old polymarket project.)"""
from .base import Strategy
from .maker_rebate import MakerRebateStrategy

_STRATEGIES = {
    "maker_rebate": MakerRebateStrategy,
}


def build_strategy(name: str) -> Strategy:
    try:
        return _STRATEGIES[name.strip().lower()]()
    except KeyError:
        raise ValueError(
            f"unknown strategy {name!r} — every-tick-single only ships maker_rebate"
        ) from None
