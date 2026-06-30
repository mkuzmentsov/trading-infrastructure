"""Segregated degen-sleeve isolation tests (experiment #19).

These are the guarantees that make a high-risk outlet safe: the core book is PHYSICALLY unable to be
harmed by the degen sleeve. Each test pins one invariant from `risk/sleeve.py`.
"""

from algo_trading_bot.risk.sleeve import SegregatedSleeves


def _prices(btc):
    return {"BTC": btc}


def test_allocation_split():
    s = SegregatedSleeves.new(100_000, degen_fraction=0.03)
    assert s.core.cash == 97_000
    assert s.degen.cash == 3_000
    assert s.degen_alloc == 3_000


def test_core_untouched_by_degen_blowup():
    """Guarantee #1: a total degen wipeout leaves core equity byte-identical."""
    s = SegregatedSleeves.new(100_000, degen_fraction=0.03, liq_floor_frac=0.30)
    # core holds nothing (flat targets); degen goes 10x long then BTC halves -> liquidation
    s.step({}, {"BTC": 10.0}, _prices(100.0), "t0")
    core_before = s.core.equity(_prices(100.0))
    s.step({}, {"BTC": 10.0}, _prices(50.0), "t1")     # -50% price * 10x = catastrophic
    assert s.core.equity(_prices(50.0)) == core_before == 97_000   # core cash never moved
    assert s.breaker.halted                                         # degen killed


def test_degen_loss_bounded_by_allocation():
    """Guarantee #2: you cannot lose more than the ring-fenced allocation, ever."""
    s = SegregatedSleeves.new(100_000, degen_fraction=0.05, liq_floor_frac=0.0)
    s.step({}, {"BTC": 20.0}, _prices(100.0), "t0")    # 20x long
    s.step({}, {"BTC": 20.0}, _prices(10.0), "t1")     # -90% price — would be deeply negative unlevered
    assert s.degen.equity(_prices(10.0)) >= 0.0        # floored at 0, not negative
    total = s.equity(_prices(10.0))
    assert total >= 95_000                              # at worst we lost the 5% sleeve, nothing more


def test_killswitch_halts_and_stays_halted():
    """Guarantee #3: the breaker halts on deep DD and will NOT re-open without a manual reset."""
    s = SegregatedSleeves.new(100_000, degen_fraction=0.10, degen_halt=0.90, liq_floor_frac=0.0)
    s.step({}, {"BTC": 5.0}, _prices(100.0), "t0")
    s.step({}, {"BTC": 5.0}, _prices(75.0), "t1")      # -25% * 5x = -125% notional move -> halt
    assert s.breaker.halted
    # even with a juicy signal and recovered price, a halted sleeve must NOT take a position
    s.step({}, {"BTC": 5.0}, _prices(120.0), "t2")
    assert not s.degen.positions                        # stays flat
    # only an explicit ops reset re-arms it
    s.reset_degen()
    assert not s.breaker.halted


def test_refuses_insane_allocation():
    """Refuse to ring-fence more than 25% — that's not a sleeve, that's the whole account at risk."""
    try:
        SegregatedSleeves.new(100_000, degen_fraction=0.50)
        assert False, "should have rejected a 50% degen allocation"
    except ValueError:
        pass


def test_core_compounds_independently():
    """Core can make money while degen is dead — the two equities are fully decoupled."""
    s = SegregatedSleeves.new(100_000, degen_fraction=0.03, liq_floor_frac=0.30)
    s.step({"BTC": 1.0}, {"BTC": 10.0}, _prices(100.0), "t0")   # core 1x long, degen 10x long
    s.step({"BTC": 1.0}, {"BTC": 10.0}, _prices(50.0), "t1")    # crash: degen dies, core down 50% on its BTC
    # degen halted, but core still holds its own BTC position and marks independently
    assert s.breaker.halted
    assert s.core.positions.get("BTC", 0) > 0                    # core position intact, its own P&L
