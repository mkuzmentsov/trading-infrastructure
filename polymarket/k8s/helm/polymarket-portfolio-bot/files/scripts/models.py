"""Dataclasses shared across modules."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Outcome:
    label:    str
    price:    float
    token_id: str


@dataclass
class Market:
    condition_id:  str
    question:      str
    description:   str
    volume_24h:    float
    end_date:      str
    days_to_close: float
    neg_risk:      bool
    min_size:      float
    outcomes:      list  # list[Outcome]


@dataclass
class HeldPosition:
    condition_id:  str
    token_id:      str
    outcome:       str
    question:      str
    size_shares:   float
    avg_price:     float
    current_price: float
    cash_pnl:      float
    percent_pnl:   float
    end_date:      str
    redeemable:    bool
    neg_risk:      bool
