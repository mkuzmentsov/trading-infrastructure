# openlag re-check pipeline (frozen 2026-08-29)

Question: is the pre-open locked-strike seam back? (strat-openlag.md)
1. Make sure the local raw archive `every-tick-single/data/mrec/<coin>/` is
   current (parallel per-coin `kubectl exec cat` + size+gzip verify; NEVER
   tar-over-exec).
2. `python3 extract_cl.py <coin> <mrec_dir> <coin>_cl.csv` per coin
   (parallel; ~90s/coin locally). Edit the date glob inside if needed.
3. `python3 seam_cl2.py` in the CSV dir.
Read: |z|>=1.2 EV/sh; avgask (~0.54 = stale book back / ~0.72 = priced);
stratified-null p. Supporting: seam_mid.py (moderate z), seam_early.py
(+extract_early.py, ws-10/ws-30 fire), extract_prefill.py (pre-open fill
physics), zpre.py + nulltest2.py (archive-era versions).
