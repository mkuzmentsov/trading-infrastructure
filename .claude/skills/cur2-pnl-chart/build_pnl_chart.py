#!/usr/bin/env python3
"""Build a cumulative-realized-PnL-by-coin chart for the cur+2 50c bettor fleet.

Pulls CUR2_BET_SETTLE events from the live cur2 pods (sol-cur2, eth-cur2, ...),
computes per-coin cumulative realized PnL, and renders a self-contained,
theme-aware, interactive HTML line chart (crosshair + tooltip + data table).

The kube context MUST already be Hetzner (`source .dev-env-source`); this script
only shells out to `kubectl logs`, it does not switch context.

Usage:
  python3 build_pnl_chart.py OUT.html [--coins sol,eth] [--since "YYYY-MM-DD HH:MM:SS"]
                                      [--ns every-tick-single] [--from-dir DIR]

  --since   drop settlements before this UTC timestamp (default: all). The natural
            cut is the wallet top-up = the last "not enough balance" rejection, so
            starved-period no-fills don't dilute the curve. Find it with:
              kubectl logs -n every-tick-single deploy/sol-cur2-every-tick-single \\
                | grep "not enough balance" | tail -1
  --from-dir read {coin}_settle.txt (raw `kubectl logs` dumps) from DIR instead of
            hitting the pods live (for reproducible/offline rebuilds).

Settle line schema (space-separated):
  <date> <time>  INFO  CUR2_BET_SETTLE  target=.. side=UP p_up=.. outcome=UP
                 filled=10.0 shares=10 won=True pnl=5.0 day_pnl=.. live=True
Only `filled>0` rows move PnL; `pnl` is per-bet realized ($ = filled*((win?1:0)-0.50)).
"""
import argparse, json, subprocess, sys, re

# coin -> validated categorical slot (dataviz palette; see references/palette.md).
# Order blue, aqua, yellow, green maximizes adjacent-CVD; relief = direct labels (always on).
COLORS = {
    "sol": {"light": "#2a78d6", "dark": "#3987e5"},   # blue
    "eth": {"light": "#1baf7a", "dark": "#199e70"},   # aqua
    "xrp": {"light": "#eda100", "dark": "#c98500"},   # yellow
    "btc": {"light": "#008300", "dark": "#008300"},   # green
}


def pull(coin, ns):
    dep = f"{coin}-cur2-every-tick-single"
    return subprocess.run(
        ["kubectl", "logs", "-n", ns, f"deploy/{dep}", "--tail=100000"],
        capture_output=True, text=True,
    ).stdout


def parse_settles(text, since):
    rows = []
    for ln in text.splitlines():
        if "CUR2_BET_SETTLE" not in ln:
            continue
        ts = " ".join(ln.split()[:2])            # "YYYY-MM-DD HH:MM:SS"
        if since and ts < since:
            continue
        f = re.search(r"filled=([-\d.]+)", ln)
        p = re.search(r"pnl=([-\d.]+)", ln)
        w = re.search(r"won=(\w+)", ln)
        if not (f and p):
            continue
        rows.append((ts, float(p.group(1)), float(f.group(1)), (w and w.group(1) == "True")))
    rows.sort()
    return rows


def series_for(rows):
    cum = fills = wins = 0
    series = []
    for ts, pnl, filled, won in rows:
        cum += pnl
        if filled > 0:
            fills += 1
            wins += 1 if won else 0
        series.append([ts.replace(" ", "T"), round(cum, 2)])
    return {
        "series": series, "fills": fills, "wins": wins,
        "final": round(cum, 2), "winrate": round(100 * wins / fills, 1) if fills else 0,
    }


def build(data, out, since):
    palette = ",".join(COLORS.get(c, COLORS["sol"])["light"] for c in data)
    css_vars, css_dark, legend, coins_js = [], [], [], []
    for c in data:
        css_vars.append(f"--{c}:{COLORS.get(c, COLORS['sol'])['light']};")
        css_dark.append(f"--{c}:{COLORS.get(c, COLORS['sol'])['dark']};")
        legend.append(f'<span><i style="background:var(--{c})"></i>{c}</span>')
        coins_js.append(f'{{k:"{c}",c:"var(--{c})"}}')
    html = _TMPL
    html = html.replace("__PALETTE__", palette)
    html = html.replace("__CSSVARS__", " ".join(css_vars))
    html = html.replace("__CSSDARK__", " ".join(css_dark))
    html = html.replace("__LEGEND__", "\n    ".join(legend))
    html = html.replace("__COINS__", "[" + ",".join(coins_js) + "]")
    html = html.replace("__DATA__", json.dumps(data))
    html = html.replace("__SINCE__", since or "start of logs")
    with open(out, "w") as fh:
        fh.write(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--coins", default="sol,eth")
    ap.add_argument("--since", default="")
    ap.add_argument("--ns", default="every-tick-single")
    ap.add_argument("--from-dir", default="")
    a = ap.parse_args()
    coins = [c.strip() for c in a.coins.split(",") if c.strip()]
    data = {}
    for c in coins:
        if a.from_dir:
            txt = open(f"{a.from_dir}/{c}_settle.txt").read()
        else:
            txt = pull(c, a.ns)
        rows = parse_settles(txt, a.since)
        if not rows:
            print(f"WARN {c}: 0 settlements since '{a.since}'", file=sys.stderr)
            continue
        data[c] = series_for(rows)
        print(f"{c}: fills={data[c]['fills']} wins={data[c]['wins']} "
              f"final=${data[c]['final']} winrate={data[c]['winrate']}%")
    if not data:
        sys.exit("no data — check coins/--since/kube context")
    build(data, a.out, a.since)
    print(f"wrote {a.out}")


_TMPL = r"""<title>cur+2 cumulative PnL by coin</title>
<style>
  .viz-root{ --surface-1:#fcfcfb; --surface-2:#f2f2ef; --border:#e4e3de;
    --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#8a897f;
    --pos:#008300; --neg:#e34948; --grid:#e8e7e2; __CSSVARS__
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    color:var(--text-primary); background:var(--surface-1); max-width:960px; margin:0 auto; padding:24px 20px 40px; }
  @media (prefers-color-scheme: dark){ .viz-root{ --surface-1:#1a1a19; --surface-2:#232322; --border:#34332f;
    --text-primary:#fff; --text-secondary:#c3c2b7; --text-muted:#8a897f; --pos:#3fb950; --neg:#e66767; --grid:#2c2b28; __CSSDARK__ } }
  :root[data-theme="dark"] .viz-root{ --surface-1:#1a1a19; --surface-2:#232322; --border:#34332f;
    --text-primary:#fff; --text-secondary:#c3c2b7; --text-muted:#8a897f; --pos:#3fb950; --neg:#e66767; --grid:#2c2b28; __CSSDARK__ }
  .viz-root h1{font-size:19px; margin:0 0 4px; font-weight:650; letter-spacing:-0.01em;}
  .viz-root .sub{font-size:13px; color:var(--text-secondary); margin:0 0 20px; line-height:1.5;}
  .tiles{display:flex; flex-wrap:wrap; gap:12px; margin-bottom:22px;}
  .tile{flex:1; min-width:150px; background:var(--surface-2); border:1px solid var(--border); border-radius:10px; padding:12px 14px;}
  .tile .lab{display:flex; align-items:center; gap:7px; font-size:12px; color:var(--text-secondary); margin-bottom:6px;}
  .tile .dot{width:9px; height:9px; border-radius:50%; flex:none;}
  .tile .val{font-size:24px; font-weight:680; letter-spacing:-0.02em; font-variant-numeric:tabular-nums;}
  .tile .meta{font-size:12px; color:var(--text-muted); margin-top:3px; font-variant-numeric:tabular-nums;}
  .pos{color:var(--pos);} .neg{color:var(--neg);}
  .chartwrap{position:relative; width:100%;}
  svg{display:block; width:100%; height:auto; overflow:visible;}
  .legend{display:flex; gap:18px; margin:6px 0 0 4px; font-size:13px; color:var(--text-secondary); flex-wrap:wrap;}
  .legend span{display:inline-flex; align-items:center; gap:7px;}
  .legend i{width:14px; height:3px; border-radius:2px; display:inline-block;}
  .tip{position:absolute; pointer-events:none; opacity:0; transition:opacity .08s; background:var(--surface-1);
    border:1px solid var(--border); border-radius:8px; padding:8px 10px; font-size:12px;
    box-shadow:0 4px 16px rgba(0,0,0,.14); z-index:5; font-variant-numeric:tabular-nums; min-width:132px;}
  .tip .tt{color:var(--text-muted); margin-bottom:5px; font-size:11px;}
  .tip .row{display:flex; justify-content:space-between; gap:14px; align-items:center;}
  .tip .k{display:inline-flex; align-items:center; gap:6px; color:var(--text-secondary);}
  .tip .k i{width:8px; height:8px; border-radius:50%;}
  details{margin-top:20px; font-size:13px; color:var(--text-secondary);}
  summary{cursor:pointer;} table{border-collapse:collapse; margin-top:10px; font-size:12px; font-variant-numeric:tabular-nums;}
  th,td{border:1px solid var(--border); padding:4px 9px; text-align:right;} th:first-child,td:first-child{text-align:left;}
</style>
<div class="viz-root" data-palette="__PALETTE__">
  <h1>cur+2 cumulative realized PnL, by coin</h1>
  <p class="sub">50c bettor · $5/order · one point per settled 5-minute market. Window: since <b>__SINCE__</b>.</p>
  <div class="tiles" id="tiles"></div>
  <div class="chartwrap">
    <svg id="chart" viewBox="0 0 900 340" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Cumulative PnL over time"></svg>
    <div class="tip" id="tip"></div>
  </div>
  <div class="legend">
    __LEGEND__
    <span style="color:var(--text-muted)">— zero line = flat</span>
  </div>
  <details><summary>Data table</summary>
    <table id="tbl"><thead><tr><th>coin</th><th>fills</th><th>wins</th><th>win%</th><th>final</th><th>peak</th><th>trough</th></tr></thead><tbody></tbody></table>
  </details>
</div>
<script>
const DATA=__DATA__, COINS=__COINS__;
const fmt=v=>(v>=0?'+$':'−$')+Math.abs(v).toFixed(2), parse=s=>Date.parse(s+'Z');
const tiles=document.getElementById('tiles'); let net=0, totf=0;
COINS.forEach(({k,c})=>{const d=DATA[k]; if(!d)return; net+=d.final; totf+=d.fills;
  tiles.insertAdjacentHTML('beforeend',`<div class="tile"><div class="lab"><span class="dot" style="background:${c}"></span>${k}</div>`+
  `<div class="val ${d.final>=0?'pos':'neg'}">${fmt(d.final)}</div><div class="meta">${d.wins}/${d.fills} fills won · ${d.winrate}%</div></div>`);});
tiles.insertAdjacentHTML('beforeend',`<div class="tile"><div class="lab">net</div><div class="val ${net>=0?'pos':'neg'}">${fmt(net)}</div><div class="meta">${totf} total fills</div></div>`);
const tb=document.querySelector('#tbl tbody');
COINS.forEach(({k})=>{const d=DATA[k]; if(!d)return; const ys=d.series.map(p=>p[1]);
  tb.insertAdjacentHTML('beforeend',`<tr><td>${k}</td><td>${d.fills}</td><td>${d.wins}</td><td>${d.winrate}%</td><td>${fmt(d.final)}</td><td>${fmt(Math.max(...ys))}</td><td>${fmt(Math.min(...ys))}</td></tr>`);});
const svg=document.getElementById('chart'), W=900,H=340,M={t:16,r:64,b:34,l:52}, iw=W-M.l-M.r, ih=H-M.t-M.b;
const pts=[]; COINS.forEach(({k})=>{if(DATA[k])DATA[k].series.forEach(p=>pts.push(p));});
const allT=pts.map(p=>parse(p[0])), t0=Math.min(...allT), t1=Math.max(...allT);
const allY=pts.map(p=>p[1]); let y0=Math.min(...allY,0), y1=Math.max(...allY,0); const pad=(y1-y0)*0.08||1; y0-=pad; y1+=pad;
const sx=t=>M.l+(t-t0)/(t1-t0||1)*iw, sy=v=>M.t+(y1-v)/(y1-y0)*ih;
const NS='http://www.w3.org/2000/svg', mk=(n,a)=>{const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);return e;};
function ticks(lo,hi,n){const raw=(hi-lo)/n,mag=Math.pow(10,Math.floor(Math.log10(raw)));const nm=raw/mag,st=(nm<1.5?1:nm<3?2:nm<7?5:10)*mag;const o=[];for(let v=Math.ceil(lo/st)*st;v<=hi;v+=st)o.push(+v.toFixed(6));return o;}
ticks(y0,y1,5).forEach(v=>{const y=sy(v),z=Math.abs(v)<1e-9;svg.appendChild(mk('line',{x1:M.l,x2:M.l+iw,y1:y,y2:y,stroke:z?'var(--text-muted)':'var(--grid)','stroke-width':z?1.4:1}));
  const tx=mk('text',{x:M.l-9,y:y+4,'text-anchor':'end','font-size':11,fill:'var(--text-muted)'});tx.textContent=(v>=0?'$':'−$')+Math.abs(v).toFixed(0);svg.appendChild(tx);});
for(let h=0;;h+=3){const t=t0+h*3600e3; if(t>t1)break; const d=new Date(t);const tx=mk('text',{x:sx(t),y:H-12,'text-anchor':'middle','font-size':11,fill:'var(--text-muted)'});tx.textContent=String(d.getUTCHours()).padStart(2,'0')+':00';svg.appendChild(tx);}
COINS.forEach(({k,c})=>{const d=DATA[k]; if(!d)return; const P=d.series.map(p=>[sx(parse(p[0])),sy(p[1])]);
  svg.appendChild(mk('path',{d:P.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' '),fill:'none',stroke:c,'stroke-width':2,'stroke-linejoin':'round','stroke-linecap':'round'}));
  const last=P[P.length-1],lv=d.series[d.series.length-1][1];
  svg.appendChild(mk('circle',{cx:last[0],cy:last[1],r:3.5,fill:c,stroke:'var(--surface-1)','stroke-width':2}));
  const lt=mk('text',{x:last[0]+8,y:last[1]+4,'font-size':12,'font-weight':600,fill:c});lt.textContent=k+' '+fmt(lv);svg.appendChild(lt);});
const tip=document.getElementById('tip'),cross=mk('line',{x1:0,x2:0,y1:M.t,y2:M.t+ih,stroke:'var(--text-muted)','stroke-width':1,opacity:0});svg.appendChild(cross);
const hd={};COINS.forEach(({k,c})=>{if(!DATA[k])return;const d=mk('circle',{r:4.5,fill:c,stroke:'var(--surface-1)','stroke-width':2,opacity:0});svg.appendChild(d);hd[k]=d;});
const near=(s,t)=>{let b=s[0],bd=1/0;for(const p of s){const d=Math.abs(parse(p[0])-t);if(d<bd){bd=d;b=p;}}return b;};
svg.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect(),px=(e.clientX-r.left)/r.width*W;if(px<M.l||px>M.l+iw){hide();return;}
  const t=t0+(px-M.l)/iw*(t1-t0);cross.setAttribute('x1',sx(t));cross.setAttribute('x2',sx(t));cross.setAttribute('opacity',1);let rows='';
  COINS.forEach(({k,c})=>{if(!DATA[k])return;const p=near(DATA[k].series,t);hd[k].setAttribute('cx',sx(parse(p[0])));hd[k].setAttribute('cy',sy(p[1]));hd[k].setAttribute('opacity',1);
    rows+=`<div class="row"><span class="k"><i style="background:${c}"></i>${k}</span><b>${fmt(p[1])}</b></div>`;});
  const dt=new Date(t);tip.innerHTML=`<div class="tt">${String(dt.getUTCMonth()+1).padStart(2,'0')}-${String(dt.getUTCDate()).padStart(2,'0')} ${String(dt.getUTCHours()).padStart(2,'0')}:${String(dt.getUTCMinutes()).padStart(2,'0')} UTC</div>${rows}`;
  tip.style.opacity=1;const tw=tip.offsetWidth,left=Math.min(Math.max(px/W*r.width-tw/2,0),r.width-tw);tip.style.left=left+'px';tip.style.top=(sy(y1)/H*r.height-4)+'px';});
svg.addEventListener('mouseleave',hide);
function hide(){cross.setAttribute('opacity',0);tip.style.opacity=0;Object.values(hd).forEach(d=>d.setAttribute('opacity',0));}
</script>
"""

if __name__ == "__main__":
    main()
