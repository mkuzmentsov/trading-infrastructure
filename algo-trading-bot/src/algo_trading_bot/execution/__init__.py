"""Execution layer (§2.6, §7.3). Idempotent order management that always works
toward the LATEST target; cancels/replaces stale in-flight orders."""
