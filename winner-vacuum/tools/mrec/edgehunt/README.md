# edgehunt — Agent B scripts (2026-09-07/08), see docs/strat-edge-hunt-5m-20260907.md
Run from a scratch dir with `pq` -> the mrec parquet build (tools/mrec/README.md) and `led/` = the 7
vacmaker event ledgers pulled read-only (pattern in tools/fillphys.py docstring).
- tsc_extract.py  raw mrecev -> every tick_size_change + [-3,+15]s book/trade window (1 GB parquet)
- tsc_an3.py      book state in the 5 s after each tick change (crossed? fine levels? prints vs pre-book)
- ledload.py / led_an.py   live ledger -> fills_era.parquet; class/band/tl/clip/hour tables
- latesim2.py     house-fill-model replay (bug #27) of widening the fire window below tl=3
- wallets.py      data-api late-window taker wallet census (sampled bars)
The inline censuses quoted in the doc (post-close prints, underdog lottery grid, cross-coin est,
UTC hole, ladder restriction) are short pandas one-offs reproduced verbatim in the doc's appendix.
