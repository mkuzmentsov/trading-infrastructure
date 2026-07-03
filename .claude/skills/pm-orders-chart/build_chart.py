#!/usr/bin/env python3
"""Polymarket every-tick chart: 5m closes + chop/trend shading + fill outcomes.

Usage: python3 build_chart.py <events_dir> <out_html> [start_utc_ms]
  events_dir: dir with {btc,eth,sol,xrp}_snap.jsonl (dumped from every-tick-single pods:
    kubectl exec -n every-tick-single deploy/{coin}-every-tick-single -- \
      cat /app/logs/logs-training-events.jsonl > {coin}_snap.jsonl)
  start_utc_ms: chart window start (default: 4h ago rounded to 5m)

Regime: per-coin percentiles of |5m move| in window — chop <= p60, trend >= p85.
Fill markers: settled bar start = floor(settle.ts/300)*300 - 300 (settle fires at
bar end; its market_start_ts belongs to the NEXT bar — do not join on it).
"""
import json, sys, time, urllib.request

def get(url):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "curl/8"}), timeout=20).read())

def main():
    events_dir, out_html = sys.argv[1], sys.argv[2]
    start = int(sys.argv[3]) if len(sys.argv) > 3 else (int(time.time()) - 4*3600)//300*300*1000
    out = {}
    for sym, coin in [('BTCUSDT','btc'),('ETHUSDT','eth'),('SOLUSDT','sol'),('XRPUSDT','xrp')]:
        kl = get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=5m&startTime={start}&limit=120")
        bars = [{'t': int(k[0]/1000), 'o': float(k[1]), 'c': float(k[4])} for k in kl]
        rets = sorted(abs(b['c']/b['o']-1)*1e4 for b in bars)
        p60, p85 = rets[int(len(rets)*.6)], rets[int(len(rets)*.85)]
        for b in bars:
            r = abs(b['c']/b['o']-1)*1e4
            b['reg'] = 'trend' if r >= p85 else ('chop' if r <= p60 else 'mid')
        fills = []
        try:
            fh = open(f'{events_dir}/{coin}_snap.jsonl')
        except FileNotFoundError:
            fh = []
        for line in fh:
            try: e = json.loads(line)
            except Exception: continue
            if e.get('event') == 'paper_bar_settle' and (e.get('positions') or []):
                bar_start = int(e['ts']//300*300) - 300
                for po in e['positions']:
                    fills.append({'t': bar_start, 'side': po['direction'][0],
                                  'win': bool(po['win'] or po['exit_kind'] == 'tp')})
        out[coin] = {'bars': bars, 'fills': fills, 'p60': round(p60,1), 'p85': round(p85,1)}
    html = TEMPLATE.replace('PAYLOAD', json.dumps(out))
    open(out_html, 'w').write(html)
    print(f"written {out_html}: " + " ".join(f"{c}:{len(v['fills'])}f" for c, v in out.items()))

TEMPLATE = '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>5m bars + orders — chop/trend + win/loss</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>body{font-family:-apple-system,sans-serif;background:#111;color:#eee;margin:1.5rem}
.wrap{max-width:1000px;margin:0 auto}h2{font-weight:600;margin-bottom:.2rem}
h3{margin:1.2rem 0 .2rem;font-weight:600}
.legend{font-size:.85rem;color:#bbb;margin-bottom:.8rem}
.legend span{display:inline-block;width:12px;height:12px;margin:0 4px -1px 10px;border-radius:2px}</style>
</head><body><div class="wrap">
<h2>5-minute closes + our orders</h2>
<div class="legend">bg: <span style="background:rgba(20,200,90,.15)"></span>chop <span style="background:rgba(240,70,70,.15)"></span>trend ·
markers: <b style="color:#2ecc71">U/D won</b> · <b style="color:#ff5b5b">U/D lost</b></div>
<div id="charts"></div></div>
<script>
const DATA=PAYLOAD;
function hhmm(t){const d=new Date(t*1000);return String(d.getUTCHours()).padStart(2,"0")+":"+String(d.getUTCMinutes()).padStart(2,"0")}
const deco={id:"deco",afterDatasetsDraw(ch,args,opts){
  const {ctx,chartArea:a,scales:{x,y}}=ch;
  opts.bars.forEach((b,i)=>{
    if(b.reg!=="mid"){
      const w=(x.getPixelForValue(1)-x.getPixelForValue(0));
      ctx.save();ctx.globalCompositeOperation="destination-over";
      ctx.fillStyle=b.reg==="chop"?"rgba(20,200,90,.15)":"rgba(240,70,70,.15)";
      ctx.fillRect(x.getPixelForValue(i)-w/2,a.top,w,a.bottom-a.top);ctx.restore();
    }
  });
  opts.fills.forEach(f=>{
    const i=opts.bars.findIndex(b=>b.t===f.t); if(i<0)return;
    const px=x.getPixelForValue(i), py=y.getPixelForValue(opts.bars[i].c);
    ctx.fillStyle=f.win?"#2ecc71":"#ff5b5b";
    ctx.font="bold 12px sans-serif";ctx.textAlign="center";
    ctx.fillText(f.side, px, py-8);
    ctx.beginPath();ctx.arc(px,py,2.4,0,7);ctx.fill();
  });
}};
for(const coin of Object.keys(DATA)){
  const d=DATA[coin];
  const div=document.createElement("div");
  div.innerHTML=`<h3>${coin.toUpperCase()} <span style="color:#888;font-size:.8rem">chop &le; ${d.p60} · trend &ge; ${d.p85} bps/5m · ${d.fills.length} fills</span></h3><canvas id="c_${coin}" height="95"></canvas>`;
  document.getElementById("charts").appendChild(div);
  const labels=d.bars.map(b=>hhmm(b.t));
  new Chart(document.getElementById("c_"+coin),{
    type:"line",
    data:{labels,datasets:[{data:d.bars.map(b=>b.c),borderColor:"#ddd",borderWidth:1.4,pointRadius:0,tension:0}]},
    options:{animation:false,plugins:{legend:{display:false},deco:{bars:d.bars,fills:d.fills}},
      scales:{x:{ticks:{maxTicksLimit:14,color:"#999"},grid:{color:"rgba(255,255,255,.05)"}},
              y:{ticks:{color:"#999"},grid:{color:"#222"}}}},
    plugins:[deco]});
}
</script></body></html>'''

if __name__ == '__main__':
    main()
