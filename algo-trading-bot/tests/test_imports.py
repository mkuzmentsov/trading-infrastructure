"""Smoke test: every module imports cleanly (no syntax errors, no bad references).

The scaffold is full of NotImplementedError stubs — that's fine. This test only
asserts the package is internally consistent and importable.
"""

import importlib
import pkgutil

import algo_trading_bot


def test_package_imports():
    pkg = algo_trading_bot
    failures = []
    for mod in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        try:
            importlib.import_module(mod.name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{mod.name}: {exc!r}")
    assert not failures, "import failures:\n" + "\n".join(failures)
