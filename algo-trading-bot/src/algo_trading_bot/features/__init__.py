"""Feature & label layer (§2.2). Point-in-time features; triple-barrier labels.

Lookahead in feature calc is the most common, most fatal ML-trading bug (§2.2).
Every feature here must be computable from data with ``knowable_at <= now``.
"""
