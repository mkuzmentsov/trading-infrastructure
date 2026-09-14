#!/usr/bin/env python3
"""Build the dashboard dataset for ONE Polymarket crypto up/down bar.

    python3 build_dash.py <coin> <slug|ws> [--outdir DIR] [--no-pod] [--no-pull]

Emits <outdir>/dash.json (meta + columnar series + binance + prints), ready for
assemble.py. Recon math is delegated to the committed winner-vacuum/tools/mrec
pipeline so this never re-derives the settlement windows by hand.
"""
import argparse, gzip, json, os, re, subprocess, sys, time
import numpy as np, pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
MREC = os.path.join(REPO, "winner-vacuum", "tools", "mrec")
ROOT = os.path.join(REPO, "every-tick-single", "data", "mrec")
VENUE = os.path.join(REPO, "every-tick-single", "data", "pq-venue")
NS = "every-tick-single"
sys.path.insert(0, MREC)
import ev2pq  # noqa: E402  (committed parser: trades / RES / BAR / RB)

PRE_S, POST_S = 1250, 740       # how far either side of the bar to chart
HI_LO, HI_HI = -45, 75          # keep the full 10 Hz tape inside this tl-to-close band


def hours_for(ws):
    out, t = [], ws + 300 - PRE_S
    while t <= ws + 300 + POST_S:
        out.append(time.strftime("%Y%m%d-%H", time.gmtime(t)))
        t += 3600
    out.append(time.strftime("%Y%m%d-%H", time.gmtime(ws + 300 + POST_S)))
    return sorted(set(out))


def ensure_files(coin, hours, pull=True):
    """Local mrec hours, pulled from the recorder pod when the drain hasn't run yet."""
    d = os.path.join(ROOT, coin)
    os.makedirs(d, exist_ok=True)
    have = []
    for h in hours:
        for kind in ("mrec", "mrecev"):
            f = f"{coin}-{kind}-{h}.jsonl.gz"
            p = os.path.join(d, f)
            if os.path.exists(p):
                have.append(p); continue
            if not pull:
                print(f"  missing (not pulled): {f}"); continue
            pod = f"deploy/{coin}-mrec-{NS}" if "mrec" not in coin else f"deploy/{coin}-{NS}"
            print(f"  pulling {f} from {pod} ...")
            with open(p, "wb") as fh:
                r = subprocess.run(["kubectl", "exec", "-n", NS, pod, "--",
                                    "cat", f"/app/logs/raw/{f}"], stdout=fh)
            if r.returncode != 0 or os.path.getsize(p) == 0:
                os.remove(p); print(f"  !! not available on the pod yet: {f}"); continue
            if subprocess.run(["gzip", "-t", p]).returncode != 0:
                os.remove(p); print(f"  !! corrupt download: {f}"); continue
            have.append(p)
    return sorted(set(have))


def snap_rows(files, ws):
    rows = []
    for p in files:
        if "-mrec-" not in p:
            continue
        with gzip.open(p, "rt") as f:
            for l in f:
                if '"SNAP"' not in l:
                    continue
                try:
                    d = json.loads(l)
                except Exception:
                    continue
                if d.get("ws") == ws:
                    rows.append(d)
    rows.sort(key=lambda d: d["t"])
    return rows


def all_cl(files):
    """Chainlink 1 Hz from EVERY SNAP role — max coverage, deduped on cl_ts."""
    seen = {}
    for p in files:
        if "-mrec-" not in p:
            continue
        with gzip.open(p, "rt") as f:
            for l in f:
                if '"SNAP"' not in l:
                    continue
                try:
                    d = json.loads(l)
                except Exception:
                    continue
                c, ts = d.get("cl"), d.get("cl_ts")
                if c is None or ts is None:
                    continue
                seen.setdefault(int(ts), float(c))
    return pd.DataFrame({"cl_ts": list(seen.keys()), "cl": list(seen.values())}).sort_values("cl_ts")


def run_recon(coin, ws, files, pq):
    """res.parquet + cl.parquet, then the COMMITTED recon.py — never re-derive the windows."""
    os.makedirs(pq, exist_ok=True)
    R = [ev2pq.do_snapmeta(p)[0] for p in files if "-mrec-" in p]
    res = pd.concat(R, ignore_index=True)
    res.to_parquet(f"{pq}/res.parquet", index=False)
    cl = all_cl(files); cl.insert(0, "coin", coin)
    cl.to_parquet(f"{pq}/cl.parquet", index=False)
    env = dict(os.environ, MREC_PQ=pq)
    subprocess.run([sys.executable, os.path.join(MREC, "recon.py")], env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rec = pd.read_parquet(f"{pq}/barrecon.parquet")
    row = rec[rec.ws == ws]
    win = res[res.ws == ws].win.iloc[0] if (res.ws == ws).any() else None
    if row.empty:
        return {"win": win, "strike": None, "final": None, "margin_bps": None,
                "sobs": None, "fobs": None}
    r = row.iloc[0]
    return {"win": win or r.win, "strike": float(r.strike), "final": float(r.final),
            "margin_bps": float(r.margin_bps), "sobs": int(r.sobs), "fobs": int(r.fobs)}


def binance(coin, ws, hours):
    """Raw bookTicker — NEVER resample to 1 s (see the skill's gotcha #1)."""
    end = ws + 300
    frames = []
    for h in hours:
        p = os.path.join(VENUE, "bin", "bookTicker", f"{coin}-{h}.parquet")
        if os.path.exists(p):
            frames.append(pd.read_parquet(p))
            continue
        raw = os.path.join(ROOT, coin, f"{coin}-brec-{h}.jsonl.gz")   # pre-conversion fallback
        if os.path.exists(raw):
            rr = []
            with gzip.open(raw, "rt") as f:
                for l in f:
                    if "bookTicker" not in l:
                        continue
                    d = json.loads(l); m = d["m"]
                    rr.append((d["t"], float(m["b"]), float(m["a"])))
            if rr:
                frames.append(pd.DataFrame(rr, columns=["t", "bid", "ask"]))
    if not frames:
        return [], []
    bt = pd.concat(frames, ignore_index=True)
    bt = bt[(bt.t >= end - PRE_S) & (bt.t <= end + POST_S)].sort_values("t")
    ts, mids, prev = [], [], None
    for t, mid in zip(bt.t.values, (bt.bid.values + bt.ask.values) / 2):
        step = 0.0 if (end + HI_LO <= t <= end + HI_HI) else 1.0
        if prev is None or t - prev >= step:
            ts.append(round(t - end, 2)); mids.append(round(float(mid), 8)); prev = t
    return ts, mids


def prints_for(coin, ws, files):
    end = ws + 300
    out = []
    for p in files:
        if "-mrecev-" not in p:
            continue
        tr, _ = ev2pq.do_ev(p)
        tr = tr[tr.ws == ws]
        for _, r in tr.iterrows():
            out.append({"t": round(float(r.mts) - end, 3), "tok": r.tok,
                        "px": float(r.px), "sz": round(float(r.sz), 3)})
    out.sort(key=lambda x: x["t"])
    return out


def pod_entries(coin, ws):
    """The bot's own decisions. The ledger is the only trustworthy source of $.

    A timeout here almost always means kubectl is pointed at the dead EKS cluster:
    run `cd <repo root> && source ./.dev-env-source` in the SAME shell first.
    """
    pod = f"deploy/{coin}-vacmaker-{NS}"
    # the live file only holds TODAY — older bars live in the rotated daily .gz,
    # and a bar near midnight can have its VERIFY in the next day's file
    days = {time.strftime("%Y-%m-%d", time.gmtime(ws + off))
            for off in (0, 1800, 86400)}
    gz = " ".join(f"/app/logs/logs-training-events.jsonl.{d}.gz" for d in sorted(days))
    cmd = (f"{{ zcat {gz} 2>/dev/null; cat /app/logs/logs-training-events.jsonl 2>/dev/null; }}"
           f" | grep {ws}")
    try:
        r = subprocess.run(["kubectl", "exec", "-n", NS, pod, "--", "sh", "-c", cmd],
                           capture_output=True, text=True, timeout=180)
    except Exception as e:
        print("  pod log unavailable:", e)
        print("  -> if this timed out: source ./.dev-env-source first (kubectl context trap)")
        return [], None
    ev = []
    for l in r.stdout.splitlines():
        try:
            d = json.loads(l)
        except Exception:
            continue
        if d.get("bar") == ws:
            ev.append(d)
    end = ws + 300
    settle = {d["ev"]: d for d in ev if d["ev"] in ("PF_TE_LIVE_SETTLE", "PF_TE_SETTLE")}
    out = []
    for d in ev:
        e = d["ev"]
        if e == "PF_TE_WHALE_ORDER":
            s = settle.get("PF_TE_LIVE_SETTLE", {})
            px = round(d["avg_px"], 4) if d.get("avg_px") is not None else None
            sh = round(d["filled"], 4) if d.get("filled") is not None else None
            fee = (sh or 0) * 0.07 * (px or 0) * (1 - (px or 0))
            out.append({"event": e, "kind": "live", "t": -float(d["tl"]),
                        "side": d["side"], "px": px, "sh": sh, "est_bps": d.get("est_bps"),
                        "result": "LOST" if (s.get("pnl", 0) < 0) else "WON",
                        "pnl": s.get("pnl"), "fee": round(fee, 4),
                        "seen_ask": d.get("seen_ask"), "req_px": d.get("req_px"),
                        "ms": d.get("ms"), "note": ""})
        elif e == "PF_TE_BET":
            s = settle.get("PF_TE_SETTLE", {})
            out.append({"event": e + " (paper)", "kind": "paper", "t": -float(d["tl"]),
                        "side": d["side"], "px": d.get("px"), "sh": d.get("sh"),
                        "est_bps": d.get("twap_bps"),
                        "result": "WON" if (s.get("pnl", 0) > 0) else "LOST",
                        "pnl": s.get("pnl"), "note": ""})
        elif e == "PF_TE_WHALE_DELAY":
            out.append({"event": e, "kind": "blocked", "t": -float(d["tl"]),
                        "side": d["side"], "px": d.get("ask"), "sh": None,
                        "est_bps": d.get("est_bps"), "result": "BLOCKED",
                        "pnl": None, "note": ""})
    out.sort(key=lambda x: x["t"])
    ver = next((d for d in ev if d["ev"] == "PF_TE_VERIFY"), None)
    return out, ver


def defaults(meta, prints):
    """Fill the narrative slots so a bare run already renders a complete page.
    Override any of these by editing dash.json before assemble.py."""
    from datetime import datetime, timezone
    try:
        from zoneinfo import ZoneInfo
        kyiv = ZoneInfo("Europe/Kyiv"); et = ZoneInfo("America/New_York")
    except Exception:
        kyiv = et = timezone.utc
    ws, end, C = meta["ws"], meta["end"], meta["coin"].upper()
    o = datetime.fromtimestamp(ws, timezone.utc); c = datetime.fromtimestamp(end, timezone.utc)
    meta["venue_label"] = "polymarket \u00b7 " + meta["slug"]
    meta["title_html"] = (f'{C} Up or Down <span class="q">\u2014 '
                          f'{o.strftime("%-d %b %Y")}, {o.strftime("%H:%M")}\u2013'
                          f'{c.strftime("%H:%M")}&nbsp;UTC</span>')
    meta["page_title"] = f'{C.title()} {o.strftime("%H:%M")} Bar Autopsy'
    meta["subtitle"] = (
        f'{o.astimezone(kyiv).strftime("%H:%M")}\u2013{c.astimezone(kyiv).strftime("%H:%M")} Kyiv \u00b7 '
        f'{o.astimezone(et).strftime("%-I:%M")}\u2013{c.astimezone(et).strftime("%-I:%M %p")} ET \u00b7 '
        f'settled on a 60-second Chainlink TWAP')

    # taker-side aggregate straight off the print tape
    winT = "U" if meta["win"] == "UP" else "D"
    gross = fee = notl = shares = 0.0
    for p in prints:
        isw = (p["tok"] == winT)
        gross += (1 - p["px"]) * p["sz"] if isw else -p["px"] * p["sz"]
        fee += p["sz"] * 0.07 * p["px"] * (1 - p["px"])
        notl += p["px"] * p["sz"]; shares += p["sz"]
    net = gross - fee

    def f(label, value, sub=None, tone=None):
        return {"label": label, "value": value, "sub": sub, "tone": tone}

    def px(v, sig=8):
        """~sig significant digits — 0.0842488 and 78547.57 both need to read right."""
        a = abs(v)
        d = 2 if a == 0 else max(0, min(8, sig - 1 - int(np.floor(np.log10(a)))))
        return f"{v:.{d}f}"

    facts = []
    if meta["strike"] is not None:
        facts += [f("Strike", px(meta["strike"]), "TWAP-60 to open"),
                  f("Final",  px(meta["final"]),  "TWAP-60 to close")]
    if meta["margin_bps"] is not None:
        mb = meta["margin_bps"]
        facts.append(f("Margin", ("\u2212" if mb < 0 else "+") + f"{abs(mb):.3f} bps",
                       "a near-tie" if abs(mb) < 1 else "decisive",
                       "neg" if mb < 0 else "pos"))
    live = next((e for e in meta["entries"] if e["kind"] == "live"), None)
    if live:
        facts.append(f("Our fill", f'{live["side"]} @ {live["px"]:.2f}',
                       f'{live["sh"]:.2f} sh, T\u2212{abs(live["t"]):.1f}s'))
        if live.get("pnl") is not None:
            pn = live["pnl"]; fe = live.get("fee") or 0.0
            facts.append(f("Our P&L", ("\u2212$" if pn < 0 else "+$") + f"{abs(pn):.2f}",
                           f'ledger; \u2212${abs(pn - fe):.2f} after the taker fee'
                           if pn < 0 else f'ledger; +${pn - fe:.2f} net of fee',
                           "neg" if pn < 0 else "pos"))
    if prints:
        facts.append(f("All takers", ("\u2212$" if net < 0 else "+$") + f"{abs(net):.2f}",
                       f"{len(prints)} prints, ${notl:.0f} notional",
                       "neg" if net < 0 else "pos"))
    meta["facts"] = facts
    meta["taker_net"] = round(net, 2)

    meta["source_html"] = (
      "<p><b>Source.</b> mrec v2 recorder tape for <code>" + meta["coin"] + "</code>, via the committed "
      "parquet pipeline (<code>ev2pq</code> \u2192 <code>recon.py</code>). Book and feeds are the "
      "recorder's 10&nbsp;Hz <code>SNAP</code> stream, sampled at 10&nbsp;Hz inside T\u221245s\u2026T+75s and "
      "1&nbsp;Hz outside. Binance is the raw <code>bookTicker</code> tape, <b>not</b> resampled to 1&nbsp;s \u2014 "
      "these bars can turn over in ~100&nbsp;ms and second-bucketing destroys that. Entries and P&amp;L come "
      "from the live pod's own event log, never from a replay. Margin from " + meta.get("margin_src","") + ".</p>"
      "<p>The recorder follows a market from ~20 minutes before it opens through ~7 minutes after it closes, "
      "so the pre-open and post-close book is real data. The book lines stop where the venue stops quoting.</p>")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("coin")
    ap.add_argument("market", help="slug (…-5m-<ws>) or the bare ws epoch")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--no-pod", action="store_true", help="skip the bot's event log")
    ap.add_argument("--no-pull", action="store_true", help="never kubectl-pull a missing hour")
    a = ap.parse_args()

    m = re.search(r"(\d{9,11})", a.market)
    if not m:
        sys.exit("cannot read a window-start epoch out of: " + a.market)
    ws = int(m.group(1)); end = ws + 300
    slug = a.market if "-" in a.market else f"{a.coin}-updown-5m-{ws}"
    os.makedirs(a.outdir, exist_ok=True)

    hrs = hours_for(ws)
    print(f"{a.coin} ws={ws} ({time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ws))} UTC) hours={hrs}")
    files = ensure_files(a.coin, hrs, pull=not a.no_pull)
    if not files:
        sys.exit("no mrec files for that window")

    rec = run_recon(a.coin, ws, files, os.path.join(a.outdir, "pq"))
    print("  recon:", rec)

    rows = snap_rows(files, ws)
    if not rows:
        sys.exit(f"no SNAP rows for ws={ws} — wrong coin, or the tape does not cover it")
    # full 10 Hz where the decision happens, 1 Hz either side
    kept, prev = [], None
    for d in rows:
        rel = d["t"] - end                       # seconds relative to close
        step = 0.0 if (HI_LO <= rel <= HI_HI) else 1.0
        if prev is None or d["t"] - prev >= step:
            kept.append(d); prev = d["t"]
    print(f"  snap rows {len(rows)} -> {len(kept)} sampled; roles "
          f"{sorted(set(d['role'] for d in rows))}")

    def col(k, nd):
        return [None if d.get(k) is None else round(float(d[k]), nd) for d in kept]

    bt, bm = binance(a.coin, ws, hrs)
    pr = prints_for(a.coin, ws, files)
    ents, ver = ([], None) if a.no_pod else pod_entries(a.coin, ws)
    print(f"  binance {len(bt)} · prints {len(pr)} · entries {len(ents)}")

    # PF_TE_VERIFY carries the VENUE's own strike/close. It outranks our recon,
    # which averages only the ticks the recorder received (~0.03-0.5 bps off).
    margin_src = "recon (recorder ticks)"
    if ver and ver.get("ok"):
        rec["strike"] = float(ver["true_strike"]); rec["final"] = float(ver["true_close"])
        rec["margin_bps"] = float(ver["true_move_bps"])
        margin_src = "PF_TE_VERIFY (venue truth)"
    print(f"  margin {rec['margin_bps']} from {margin_src}")

    out = {
        "meta": {
            "slug": slug, "coin": a.coin, "ws": ws, "end": end,
            "win": rec["win"], "strike": rec["strike"], "final": rec["final"],
            "margin_bps": rec["margin_bps"], "sobs": rec["sobs"], "fobs": rec["fobs"],
            "margin_src": margin_src,
            "strike_win": [-362, -303], "final_win": [-62, -3],
            "utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(ws)),
            "entries": ents, "facts": [], "title_html": "", "subtitle": "",
            "page_title": "", "source_html": "",
        },
        "t": [round(d["t"] - end, 2) for d in kept],
        "role": [d["role"] for d in kept],
        "ub": col("ub", 3), "ua": col("ua", 3), "db": col("db", 3), "da": col("da", 3),
        "ubs": col("ubs", 1), "uas": col("uas", 1), "dbs": col("dbs", 1), "das": col("das", 1),
        "cl": col("cl", 8), "tw": col("tw", 8), "sp": col("spot", 6),
        "bt": bt, "bm": bm, "prints": pr,
    }
    out["meta"] = defaults(out["meta"], pr)
    p = os.path.join(a.outdir, "dash.json")
    json.dump(out, open(p, "w"), separators=(",", ":"))
    print(f"wrote {p} ({os.path.getsize(p)//1024} KB)")


if __name__ == "__main__":
    main()
