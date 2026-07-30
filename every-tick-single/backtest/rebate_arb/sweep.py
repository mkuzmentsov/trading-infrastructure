"""Grid over the two-sided maker-quote configuration space.

Reads the compacted mrec cache (print-exact book + trades, 100ms, with ground
truth resolution). Every number here is a FIFO-queue simulation against real
taker prints — not the 1-minute mid proxy that produced the earlier
"pre-open two-sided is ~breakeven" estimate.
"""
import sys

import fast

COINS = fast.COINS


def hdr(t):
    print("\n" + "=" * 118)
    print(t)
    print("=" * 118)


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    mkts = fast.n_markets(COINS)
    print(f"universe: {mkts} resolved markets across {len(COINS)} coins")

    if which in ("all", "role"):
        hdr("A. ROLE x CANCEL RULE at 0.50/0.50 (the classic farmer config)")
        for entry in ("next3", "next2", "next1", "cur"):
            for cancel in (True, False):
                r = fast.run(COINS, 0.50, 0.50, 100.0, entry, cancel)
                tag = f"{entry} {'cancel@open' if cancel else 'hold-to-expiry'}"
                print(fast.summarize(r, tag, mkts))

    if which in ("all", "price"):
        hdr("B. SYMMETRIC PRICE GRID (entry=next2, cancel@open)")
        for p in (0.52, 0.51, 0.50, 0.49, 0.48, 0.47, 0.46, 0.45, 0.44):
            r = fast.run(COINS, p, p, 100.0, "next2", True)
            print(fast.summarize(r, f"{p:.2f}/{p:.2f} lock={1-2*p:+.2f}", mkts))

    if which in ("all", "asym"):
        hdr("C. ASYMMETRIC PAIRS (entry=next2, cancel@open)")
        for pu, pd in ((0.50, 0.49), (0.49, 0.50), (0.51, 0.48), (0.48, 0.51),
                       (0.52, 0.47), (0.47, 0.52), (0.53, 0.46), (0.46, 0.53)):
            r = fast.run(COINS, pu, pd, 100.0, "next2", True)
            print(fast.summarize(r, f"UP{pu:.2f}/DN{pd:.2f} lock={1-pu-pd:+.2f}", mkts))

    if which in ("all", "coin"):
        hdr("D. PER-COIN at 0.50/0.50 next2 cancel@open")
        for c in COINS:
            r = fast.run([c], 0.50, 0.50, 100.0, "next2", True)
            print(fast.summarize(r, c, fast.n_markets([c])))


if __name__ == "__main__":
    main()
