"""Risk layer (§2.5, §7.2) — ABSOLUTE PRECEDENCE over every strategy signal.

Stops, drawdown breaker, and the kill switch override everything, instantly. This
layer sits between the sized target and the OMS: it can only ever REDUCE risk
(shrink, cap, or flatten a target), never increase it.
"""
