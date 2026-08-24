"""Extract every 5m print with pre-trade book context + bar outcome.

Output: one parquet per (coin, day) in backtest/mm5m/cache/prints/.
Everything is expressed in UP-token terms:
  upx  = price of the UP token implied by the print
  tbu  = taker bought UP (True) / taker sold UP (False)
  maker PnL/share = (upx - upwon) if tbu else (upwon - upx)
"""
import gzip, json, os, sys, glob
from multiprocessing import Pool
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
MREC = os.path.abspath(os.path.join(ROOT, '..', '..', 'data', 'mrec'))
OUT = os.path.join(ROOT, 'cache', 'prints')
COINS = ['btc', 'eth', 'sol', 'xrp', 'bnb', 'doge', 'hype']
# ⚠️ 15m/1h/4h archives live in a DIFFERENT directory but the files keep the
# `<coin>-mrec-*` prefix (the writer's suffix map lacked 900) — ledger #21: a
# wrong glob is a SILENT ZERO. Pass dir + bar length explicitly.
SUBDIR = os.getenv('MREC_SUBDIR', '')        # dir suffix,  e.g. '-mrec15m'
# ⚠️ file PREFIX and DIR suffix differ per duration and are NOT the same:
#   5m  -> dir <coin>/            files <coin>-mrec-*
#   15m -> dir <coin>-mrec15m/    files <coin>-mrec-*      (writer lacked 900)
#   1h  -> dir <coin>-mrec1h/     files <coin>-mrec1h-*
# Getting this wrong is a SILENT ZERO (ledger #21).
FPREFIX = os.getenv('MREC_FPREFIX', '-mrec')
BAR = float(os.getenv('MREC_BAR', '300'))
WS_BASE = 1785000000


def res_scan(path):
    """Pass 1: (coin, ws) -> 1 if UP won else 0.

    ⚠️ The 1h/1d recorders PREDATE the RES fix and emit no RES rows (docs
    README §3). For those, derive the outcome from the settled POST-role book:
    ub > 0.5 => UP won (validated 88/88 against spot). Env DERIVE_WINS=1.
    """
    if os.getenv('DERIVE_WINS') == '1':
        return _derive_wins(path)
    out = {}
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                if '"ev":"RES"' not in line:
                    continue
                d = json.loads(line)
                out[(d['coin'], d['ws'])] = 1 if d['win'] == 'UP' else 0
    except (EOFError, OSError, gzip.BadGzipFile) as e:
        print('RESFAIL', path, e, file=sys.stderr)
    return out


def _derive_wins(path):
    """Last post-role book per bar decides the outcome."""
    last = {}
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                if '"role":"post"' not in line:
                    continue
                d = json.loads(line)
                ub, ua = d.get('ub'), d.get('ua')
                px = ub if ub is not None else (ua if ua is not None else None)
                if px is None:
                    continue
                k = (d['coin'], d['ws'])
                if k not in last or d['t'] >= last[k][0]:
                    last[k] = (d['t'], px)
    except (EOFError, OSError, gzip.BadGzipFile):
        return {}
    # only trust decisively settled books (0/1), not mid-flight ones
    return {k: (1 if px > 0.5 else 0) for k, (t, px) in last.items()
            if px > 0.9 or px < 0.1}


def extract(args):
    """Pass 2: prints from one hourly file."""
    path, wins = args
    prev = {}
    rows = []
    seen = set()
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                if '"role":"cur"' not in line:
                    continue
                d = json.loads(line)
                ws = d['ws']
                trd = d.get('trd')
                if trd:
                    p = prev.get(ws)
                    w = wins.get(ws)
                    if p is not None and w is not None:
                        ub, ua = p['ub'], p['ua']
                        ubs, uas = p['ubs'] or 0.0, p['uas'] or 0.0
                        lead = p['lead_bps']
                        for ts, tok, px, sz, side in trd:
                            k = (ts, tok, px, sz, side)
                            if k in seen:
                                continue
                            seen.add(k)
                            upx = px if tok == 'U' else 1.0 - px
                            tbu = (side == 'BUY') == (tok == 'U')
                            rows.append((
                                ws - WS_BASE,
                                BAR - (ts - ws),            # tl of the print
                                upx, sz, tbu, w,
                                np.nan if lead is None else lead,
                                np.nan if ub is None else ub,
                                np.nan if ua is None else ua,
                                ubs, uas,
                                d['t'] - ts,                # snapshot lag behind print
                            ))
                prev[ws] = d
    except (EOFError, OSError, gzip.BadGzipFile) as e:
        print('FAIL', path, e, file=sys.stderr)
        return None
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=[
        'ws', 'tl', 'upx', 'sz', 'tbu', 'upwon', 'lead', 'ub', 'ua', 'ubs', 'uas', 'lag'])
    for c in ('tl', 'upx', 'sz', 'lead', 'ub', 'ua', 'ubs', 'uas', 'lag'):
        df[c] = df[c].astype('float32')
    df['ws'] = df['ws'].astype('int32')
    df['upwon'] = df['upwon'].astype('int8')
    return df


def main():
    coins = sys.argv[1:] or COINS
    os.makedirs(OUT, exist_ok=True)
    pool = Pool(10)
    for coin in coins:
        files = sorted(glob.glob(os.path.join(MREC, coin + SUBDIR, f'{coin}{FPREFIX}-*.jsonl.gz')))
        if not files:
            print(f'{coin}: NO FILES', file=sys.stderr)
            continue
        wins = {}
        for part in pool.imap_unordered(res_scan, files, chunksize=4):
            wins.update(part)
        wins_coin = {ws: v for (c, ws), v in wins.items() if c == coin}
        print(f'{coin}: {len(files)} files, {len(wins_coin)} resolved bars', flush=True)
        # group files by day, write one parquet per day
        bydays = {}
        for p in files:
            day = os.path.basename(p).split('-')[2]
            bydays.setdefault(day, []).append(p)
        for day, dfiles in sorted(bydays.items()):
            outp = os.path.join(OUT, f'{coin}{SUBDIR}-{day}.parquet')
            if os.path.exists(outp):
                continue
            parts = [x for x in pool.imap(extract, [(p, wins_coin) for p in dfiles]) if x is not None]
            if not parts:
                continue
            df = pd.concat(parts, ignore_index=True)
            df = df.drop_duplicates(subset=['ws', 'tl', 'upx', 'sz', 'tbu'])
            df.to_parquet(outp, compression='zstd', index=False)
            print(f'  {coin} {day}: {len(df):,} prints', flush=True)
    pool.close()


if __name__ == '__main__':
    main()
