"""listing_metrics — pure characterization logic, no network."""

import math

from listing_sniper.dataset import binance_klines, cumulative_funding, listing_metrics


def _ramp(a, b, n):
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def test_pump_then_dump_path():
    # +50% peak at minute 10, then bleed below open and stay there
    closes = _ramp(1.0, 1.5, 11) + _ramp(1.5, 0.7, 51)[1:]   # minutes 0..60
    m = listing_metrics(closes)
    assert math.isclose(m["peak_ret"], 0.5, abs_tol=1e-9)
    assert m["time_to_peak_min"] == 10
    assert m["dd_from_peak"] < -0.4          # big bleed from the peak
    assert m["end_ret"] < 0                   # closed below open
    assert math.isclose(m["ret_5m"], 0.25, abs_tol=1e-6)
    assert m["dumped_from_open"] is True


def test_pump_and_hold_path():
    closes = _ramp(1.0, 3.0, 120)             # monotonic up, no bleed
    m = listing_metrics(closes)
    assert m["peak_ret"] > 1.9
    assert math.isclose(m["dd_from_peak"], 0.0, abs_tol=1e-9)
    assert m["end_ret"] > 1.9
    assert m["dumped_from_open"] is False


def test_short_or_empty_input():
    assert listing_metrics([]) == {}
    assert listing_metrics([1.0]) == {}
    assert listing_metrics([0.0, 0.0]) == {}   # non-positive opens filtered out


def test_horizons_nan_when_series_too_short():
    m = listing_metrics(_ramp(1.0, 1.1, 30))   # only 30 bars -> 1h/4h/24h are NaN
    assert not math.isnan(m["ret_5m"]) and not math.isnan(m["ret_15m"])
    assert math.isnan(m["ret_1h"]) and math.isnan(m["ret_24h"])


def test_cumulative_funding_short_convention():
    # short receives positive funding, pays negative -> net = sum
    assert math.isclose(cumulative_funding(["0.01", "-0.005", "0.02"]), 0.025, abs_tol=1e-12)
    assert cumulative_funding([]) == 0.0


def test_binance_klines_uses_injected_http():
    seen = {}

    def fake(url):
        seen["url"] = url
        return [[0, "1", "2", "0.5", "1.5", "100"]]

    rows = binance_klines("PARTIUSDT", "1m", 0, 10, http=fake)
    assert rows and float(rows[0][4]) == 1.5
    assert "symbol=PARTIUSDT" in seen["url"] and "interval=1m" in seen["url"]
