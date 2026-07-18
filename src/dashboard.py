"""Build a self-contained HTML fraud-risk dashboard from scores.json.

Reads output/<TICKER>/scores.json and writes dashboard/<TICKER>.html with the
data inlined, so it opens directly in a browser (no server, no fetch). Renders
every quantitative aspect: an overall risk hero, a per-aspect meter panel for
the selected year, an aspect x year risk heatmap, the multi-year trend, the
qualitative auditor/related-party signals, key financials, and (when present)
the LLM red flags and narrative.

Usage:  python src/dashboard.py [TICKER ...]   (default: all under output/)
"""
from __future__ import annotations
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
DASH = os.path.join(ROOT, "dashboard")

TEMPLATE = r"""<meta charset="utf-8">
<title>SET Fraud & Anomaly Risk</title>
<style>
:root{
  color-scheme:light dark;
  --plane:#f9f9f7; --surface:#fcfcfb; --card:#ffffff;
  --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b; --severe:#9a1c1c;
  --accent:#2a78d6;
}
:root[data-theme="dark"], :root:where(:not([data-theme="light"])){}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme="light"])){
    --plane:#0d0d0d; --surface:#1a1a19; --card:#201f1e;
    --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b; --severe:#e06666;
    --accent:#3987e5;
  }
}
:root[data-theme="dark"]{
  --plane:#0d0d0d; --surface:#1a1a19; --card:#201f1e;
  --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --severe:#e06666; --accent:#3987e5;
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.45}
.wrap{max-width:1100px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:24px;margin:0 0 2px} h2{font-size:15px;margin:30px 0 12px;color:var(--ink2);
  text-transform:uppercase;letter-spacing:.05em;font-weight:600}
.sub{color:var(--muted);font-size:13px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px}
.row{display:flex;gap:16px;flex-wrap:wrap}
.hero{display:flex;align-items:center;gap:26px;flex-wrap:wrap}
.bignum{font-size:64px;font-weight:700;line-height:1}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;
  font-weight:600;color:#fff}
.tkbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 18px;
  padding-bottom:16px;border-bottom:1px solid var(--border)}
.tkbar .lead{font-size:13px;color:var(--muted);margin-right:4px}
.tkbtn{padding:8px 16px;border:1px solid var(--border);background:var(--surface);
  color:var(--ink);border-radius:9px;cursor:pointer;font-size:15px;font-weight:700;
  display:flex;align-items:center;gap:8px}
.tkbtn.active{background:var(--accent);color:#fff;border-color:transparent}
.tkbtn .mini{font-size:12px;font-weight:600;padding:1px 7px;border-radius:999px;color:#fff}
.yearbtns{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 14px}
.yb{padding:6px 12px;border:1px solid var(--border);background:var(--surface);
  color:var(--ink2);border-radius:8px;cursor:pointer;font-size:13px;font-variant-numeric:tabular-nums}
.yb.active{background:var(--accent);color:#fff;border-color:transparent}
.meter{margin:10px 0}
.meter .top{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.meter .lbl{font-size:13px} .meter .val{font-variant-numeric:tabular-nums;font-weight:600;font-size:13px}
.track{height:9px;background:var(--grid);border-radius:5px;margin-top:5px;overflow:hidden}
.fill{height:100%;border-radius:5px}
.meter .det{color:var(--muted);font-size:11.5px;margin-top:3px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--grid);
  font-variant-numeric:tabular-nums;white-space:nowrap}
th:first-child,td:first-child{text-align:left;font-variant-numeric:normal}
thead th{color:var(--muted);font-weight:600;border-bottom:1px solid var(--axis)}
.hm{display:grid;gap:3px;overflow-x:auto}
.hm .cell{padding:8px 6px;border-radius:6px;text-align:center;font-size:12px;
  color:#fff;font-variant-numeric:tabular-nums;min-width:56px}
.hm .rlab{color:var(--ink2);font-size:12px;text-align:left;padding:8px 6px;
  display:flex;align-items:center}
.hm .clab{color:var(--muted);font-size:12px;text-align:center;padding:2px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin-top:10px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.dot{width:11px;height:11px;border-radius:3px;display:inline-block}
.flag{border-left:3px solid var(--axis);padding:8px 12px;margin:8px 0;background:var(--surface);border-radius:0 8px 8px 0}
.flag .t{font-weight:600;font-size:13.5px} .flag .e{color:var(--ink2);font-size:12.5px;margin-top:2px}
.kv{font-size:13px;color:var(--ink2)} .kv b{color:var(--ink)}
.note{font-size:12px;color:var(--muted);margin-top:6px}
svg{display:block}
.eom{background:var(--surface);border-radius:8px;padding:10px 12px;font-size:12.5px;color:var(--ink2);margin-top:8px}
.themetoggle{position:absolute;top:16px;right:16px;font-size:12px;color:var(--muted);
  background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:5px 10px;cursor:pointer}
</style>

<button class="themetoggle" onclick="toggleTheme()">◑ theme</button>
<div class="wrap" id="app"></div>

<script>
const ALL = __ALLDATA__;
const TICKERS = Object.keys(ALL);
let DATA, A, years, sel, TK;

const BANDS = [
  {name:"low",      max:30, color:"var(--good)"},
  {name:"moderate", max:50, color:"var(--warning)"},
  {name:"elevated", max:70, color:"var(--serious)"},
  {name:"high",     max:85, color:"var(--critical)"},
  {name:"severe",   max:101,color:"var(--severe)"},
];
function band(s){ if(s==null) return {name:"n/a",color:"var(--muted)"};
  for(const b of BANDS) if(s<b.max) return b; return BANDS[BANDS.length-1]; }
function fmt(n){ return n==null?"—":Number(n).toLocaleString(undefined,{maximumFractionDigits:0}); }

const ASPECT_ORDER = ["beneish","receivables","cash_conversion","accruals","altman","leverage","governance","oneoff","intangible","piotroski"];

function meter(a){
  const s = a && a.available ? a.score : null;
  const b = band(s);
  const w = s==null?0:Math.max(2,Math.min(100,s));
  return `<div class="meter">
    <div class="top"><span class="lbl">${a.__label}</span>
      <span class="val" style="color:${b.color}">${s==null?"n/a":Math.round(s)}<span style="color:var(--muted);font-weight:400"> / 100</span></span></div>
    <div class="track"><div class="fill" style="width:${w}%;background:${b.color}"></div></div>
    <div class="det">${a.detail||""}</div></div>`;
}

function trendSVG(){
  const W=1040,H=210,pl=44,pr=16,pt=16,pb=28;
  const xs=(i)=>pl+(years.length<2?0:i*(W-pl-pr)/(years.length-1));
  const ys=(v)=>pt+(100-v)*(H-pt-pb)/100;
  const overall=years.map((y,i)=>[xs(i),ys(y.overall_score??0)]);
  const quant=years.map((y,i)=>[xs(i),ys(y.quant_composite??0)]);
  const path=(pts)=>pts.map((p,i)=>(i?"L":"M")+p[0].toFixed(1)+" "+p[1].toFixed(1)).join(" ");
  let grid="";
  [0,25,50,75,100].forEach(v=>{const yy=ys(v);
    grid+=`<line x1="${pl}" y1="${yy}" x2="${W-pr}" y2="${yy}" stroke="var(--grid)" stroke-width="1"/>
    <text x="${pl-8}" y="${yy+4}" fill="var(--muted)" font-size="11" text-anchor="end">${v}</text>`;});
  let xlab="";
  years.forEach((y,i)=>{xlab+=`<text x="${xs(i)}" y="${H-8}" fill="var(--muted)" font-size="11" text-anchor="middle">${y.year_ce}</text>`;});
  const dots=(pts,c)=>pts.map(p=>`<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="4" fill="${c}"/>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Risk score trend by year">
    ${grid}
    <path d="${path(quant)}" fill="none" stroke="var(--muted)" stroke-width="2" stroke-dasharray="4 4"/>
    <path d="${path(overall)}" fill="none" stroke="var(--critical)" stroke-width="2.5"/>
    ${dots(quant,"var(--muted)")}${dots(overall,"var(--critical)")}
    ${xlab}
    <text x="${overall[overall.length-1][0]}" y="${overall[overall.length-1][1]-10}" fill="var(--critical)" font-size="12" font-weight="600" text-anchor="end">overall risk</text>
  </svg>`;
}

function cashPanel(){
  const rows=years.filter(y=>y.aspects.cash_conversion&&y.aspects.cash_conversion.available)
    .map(y=>({ce:y.year_ce, ni:y.aspects.cash_conversion.net_income/1e6,
      cfo:y.aspects.cash_conversion.cfo/1e6, fcf:y.aspects.cash_conversion.free_cash_flow/1e6}));
  if(!rows.length) return "";
  const vals=rows.flatMap(r=>[r.ni,r.cfo,r.fcf]);
  const lo=Math.min(0,...vals), hi=Math.max(0,...vals);
  const W=1040,H=250,pl=54,pr=16,pt=14,pb=30;
  const y0=(v)=>pt+(hi-v)*(H-pt-pb)/(hi-lo);
  const gw=(W-pl-pr)/rows.length, bw=Math.min(46,gw/4);
  const series=[["ni","var(--accent)","Net income"],["cfo","var(--muted)","Reported CFO"],["fcf","var(--critical)","Free cash flow"]];
  let bars="",xlab="";
  rows.forEach((r,i)=>{
    const cx=pl+gw*i+gw/2;
    series.forEach((s,j)=>{
      const v=r[s[0]]; const yv=y0(v); const yz=y0(0);
      const x=cx+(j-1)*(bw+3)-bw/2;
      const top=Math.min(yv,yz), h=Math.abs(yv-yz);
      bars+=`<rect x="${x.toFixed(1)}" y="${top.toFixed(1)}" width="${bw}" height="${Math.max(1,h).toFixed(1)}" rx="3" fill="${s[1]}"><title>${s[2]} ${r.ce}: ${v.toFixed(0)}M฿</title></rect>`;
      bars+=`<text x="${(x+bw/2).toFixed(1)}" y="${(v<0?top+h+11:top-4).toFixed(1)}" fill="${s[1]}" font-size="10" text-anchor="middle">${v.toFixed(0)}</text>`;
    });
    xlab+=`<text x="${cx.toFixed(1)}" y="${H-9}" fill="var(--muted)" font-size="11" text-anchor="middle">${r.ce}</text>`;
  });
  const yz=y0(0);
  let grid="";
  [hi,(hi+lo)/2,lo].forEach(v=>{const yy=y0(v);
    grid+=`<line x1="${pl}" y1="${yy}" x2="${W-pr}" y2="${yy}" stroke="var(--grid)" stroke-width="1"/>
    <text x="${pl-8}" y="${yy+4}" fill="var(--muted)" font-size="11" text-anchor="end">${v.toFixed(0)}</text>`;});
  const cumNI=rows.reduce((a,r)=>a+r.ni,0), cumFCF=rows.reduce((a,r)=>a+r.fcf,0);
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Net income vs reported CFO vs free cash flow by year">
    ${grid}<line x1="${pl}" y1="${yz.toFixed(1)}" x2="${W-pr}" y2="${yz.toFixed(1)}" stroke="var(--axis)" stroke-width="1.5"/>
    ${bars}${xlab}</svg>
    <div class="legend">${series.map(s=>`<span><span class="dot" style="background:${s[1]}"></span>${s[2]} (M฿)</span>`).join("")}</div>
    <div class="eom">Across ${rows[0].ce}–${rows[rows.length-1].ce}, JKN reported <b>${cumNI.toFixed(0)}M฿</b> of cumulative net profit but <b style="color:var(--critical)">${cumFCF.toFixed(0)}M฿</b> of cumulative free cash flow. Reported operating cash flow looks healthy only because ~1bn฿/yr of non-cash content-library amortisation is added back; once the cash the library actually consumes is counted, the business burned cash every year — the gap financed by the rising debt that led to the 2023 bond default.</div>`;
}

function heatmap(){
  const cols = years.length;
  let html = `<div class="hm" style="grid-template-columns:170px repeat(${cols},1fr)">`;
  html += `<div class="clab"></div>`+years.map(y=>`<div class="clab">${y.year_ce}</div>`).join("");
  for(const key of ASPECT_ORDER){
    html += `<div class="rlab">${A[key]}</div>`;
    for(const y of years){
      const a=y.aspects[key]; const s=a&&a.available?a.score:null; const b=band(s);
      html += `<div class="cell" style="background:${s==null?'var(--grid)':b.color}" title="${A[key]} ${y.year_ce}: ${s==null?'n/a':Math.round(s)}">${s==null?'·':Math.round(s)}</div>`;
    }
  }
  html += `</div>`;
  return html;
}

function govPanel(){
  const g=years.map(y=>({ce:y.year_ce, a:y.aspects.governance||{},
    aud:(y.documents.auditor||{}), or:(y.documents.one_report||{})}));
  if(!g.some(x=>x.a.available||x.aud.available)) return "";
  const cell=(v)=>v==null||v===""?"—":v;
  const rowsrc=[
    ["Audit firm", x=>cell(x.aud.auditor_firm) + (x.aud.auditor_big4===true?' <span style="color:var(--good)">Big-4</span>':(x.aud.auditor_big4===false?' <span style="color:var(--serious)">non-Big-4</span>':''))],
    ["CPA licence #", x=>cell(x.aud.auditor_license)],
    ["Opinion", x=>cell(x.aud.opinion)+(x.aud.emphasis_of_matter?' · <span style="color:var(--serious)">EOM</span>':'')+(x.aud.going_concern?' · <span style="color:var(--critical)">GC</span>':'')],
    ["Auditor change", x=>{const r=x.a.rotation||""; const bad=/downgrad|changed/.test(r); return r?`<span style="color:${bad?'var(--critical)':'var(--ink2)'}">${r}</span>`:'—';}],
    ["Related-party refs", x=>cell(x.a.related_party_refs)],
    ["56-1 sections read", x=>x.or.available?cell((x.or.sources||[]).map(s=>s.replace(/_\d+\..*$/,'').replace(/\.[A-Za-z]+$/,'')).join(', ')):'—'],
    ["Governance risk", x=>x.a.available?`<b style="color:${band(x.a.score).color}">${Math.round(x.a.score)}</b>`:'—'],
  ];
  let h=`<table><thead><tr><th></th>`+g.map(x=>`<th>${x.ce}</th>`).join("")+`</tr></thead><tbody>`;
  for(const [lab,fn] of rowsrc){
    h+=`<tr><td>${lab}</td>`+g.map(x=>`<td style="text-align:left">${fn(x)}</td>`).join("")+`</tr>`;
  }
  return h+`</tbody></table>`;
}

function financials(){
  const rows=[["revenue","Revenue"],["net_income","Net income"],["cfo","Cash from ops"],
    ["receivables","Trade & other receivables"],["total_assets","Total assets"],
    ["intangibles_rights","Content-rights intangibles"],["total_liabilities","Total liabilities"],
    ["total_equity","Total equity"],["amortization","Amortisation"]];
  let h=`<table><thead><tr><th>THB</th>`+years.map(y=>`<th>${y.year_ce}</th>`).join("")+`</tr></thead><tbody>`;
  for(const [k,lab] of rows){
    h+=`<tr><td>${lab}</td>`+years.map(y=>`<td>${fmt(y.financials[k])}</td>`).join("")+`</tr>`;
  }
  return h+`</tbody></table>`;
}

function render(){
  const y=years[sel];
  const ob=band(y.overall_score);
  const aud=y.documents.auditor||{}, rp=y.documents.related_party||{};
  const llm=y.llm||{};

  for(const key of ASPECT_ORDER){ if(y.aspects[key]) y.aspects[key].__label=A[key]; }
  const meters = ASPECT_ORDER.filter(k=>y.aspects[k]).map(k=>meter(y.aspects[k])).join("");

  let llmHTML="";
  if(llm.available){
    const flags=(llm.top_red_flags||[]).map(f=>`<div class="flag" style="border-color:${band(({low:20,moderate:45,high:75,severe:95})[f.severity]||60).color}">
      <div class="t">${f.title} <span style="color:var(--muted);font-weight:400">· ${f.severity}</span></div>
      <div class="e">${f.evidence}</div></div>`).join("");
    const qa=llm.qualitative_aspects||{};
    const qrows=Object.entries(qa).map(([k,v])=>`<div class="meter"><div class="top">
      <span class="lbl">${k.replace(/_/g,' ')}</span>
      <span class="val" style="color:${band(v.score).color}">${v.score} / 100</span></div>
      <div class="track"><div class="fill" style="width:${Math.max(2,v.score)}%;background:${band(v.score).color}"></div></div>
      <div class="det">${v.rationale}</div></div>`).join("");
    llmHTML=`<h2>LLM assessment (${llm.model||''}) · confidence: ${llm.confidence}</h2>
      <div class="card"><div class="kv" style="margin-bottom:10px">${llm.narrative||""}</div>
      ${qrows}<div style="margin-top:14px">${flags}</div></div>`;
  } else {
    llmHTML=`<div class="note">LLM layer not run (${(DATA.llm_status||'').replace(/_/g,' ')}). Set ANTHROPIC_API_KEY and re-run <code>python src/pipeline.py</code> to add qualitative aspect scores, cited red flags, and a synthesised overall score. The quantitative scores below are fully deterministic.</div>`;
  }

  const tkbar = `<div class="tkbar"><span class="lead">Compare tickers:</span>${TICKERS.map(t=>{
    const yy=ALL[t].years, l=yy[yy.length-1]||{}, c=band(l.overall_score).color;
    return `<button class="tkbtn ${t===TK?'active':''}" onclick="setTicker('${t}')">${t}
      <span class="mini" style="background:${c}">${l.overall_score==null?'—':Math.round(l.overall_score)}</span></button>`;
  }).join("")}</div>`;

  document.getElementById("app").innerHTML=`
    ${tkbar}
    <h1>${DATA.ticker} — Fraud & Anomaly Risk</h1>
    <div class="sub">${DATA.company?DATA.company+' · ':''}Consolidated annual filings · ${years[0].year_ce}–${years[years.length-1].year_ce} · figures in ${DATA.currency} · ${DATA.year_basis} · generated ${DATA.generated_at.slice(0,10)}</div>

    <div class="yearbtns">${years.map((yy,i)=>`<button class="yb ${i===sel?'active':''}" onclick="pick(${i})">${yy.year_ce} (BE ${yy.year_be})</button>`).join("")}</div>

    <div class="row">
      <div class="card hero" style="flex:1;min-width:280px">
        <div><div class="bignum" style="color:${ob.color}">${y.overall_score==null?"—":Math.round(y.overall_score)}</div>
          <div class="sub">overall risk / 100</div></div>
        <div>
          <span class="badge" style="background:${ob.color}">${(y.overall_band||ob.name).toUpperCase()}</span>
          <div class="kv" style="margin-top:10px">Deterministic composite: <b>${y.quant_composite==null?"—":Math.round(y.quant_composite)}</b>
            <span class="sub">(mean ${fmt(y.quant_mean)}, severity ${fmt(y.quant_severity)})</span></div>
          <div class="kv">Auditor opinion: <b>${aud.available?aud.opinion:"n/a"}</b>${aud.emphasis_of_matter?' · <b style="color:var(--serious)">emphasis of matter</b>':''}${aud.going_concern?' · <b style="color:var(--critical)">going concern</b>':''}</div>
          <div class="kv">Related-party references in notes: <b>${rp.related_party_mentions??"n/a"}</b></div>
        </div>
      </div>
    </div>

    <h2>Quantitative risk by aspect — ${y.year_ce}</h2>
    <div class="card">${meters}</div>

    <h2>Multi-year trend</h2>
    <div class="card">${trendSVG()}
      <div class="legend"><span><span class="dot" style="background:var(--critical)"></span>overall risk</span>
      <span><span class="dot" style="background:var(--muted)"></span>deterministic composite</span></div></div>

    ${cashPanel() ? `<h2>Cash conversion — profit vs. free cash flow</h2><div class="card">${cashPanel()}</div>` : ""}

    <h2>Aspect × year risk heatmap</h2>
    <div class="card">${heatmap()}
      <div class="legend">
        <span><span class="dot" style="background:var(--good)"></span>low</span>
        <span><span class="dot" style="background:var(--warning)"></span>moderate</span>
        <span><span class="dot" style="background:var(--serious)"></span>elevated</span>
        <span><span class="dot" style="background:var(--critical)"></span>high</span>
        <span><span class="dot" style="background:var(--severe)"></span>severe</span></div></div>

    ${aud.available && aud.emphasis_text ? `<div class="eom"><b>Auditor emphasis of matter (${y.year_ce}):</b> ${aud.emphasis_text}…</div>`:''}

    ${govPanel() ? `<h2>Governance &amp; disclosure — auditor & 56-1 One Report</h2><div class="card" style="overflow-x:auto">${govPanel()}<div class="note" style="margin-top:8px">Auditor identity, rotation, and related-party density drawn from the auditor's report and the 56-1 One Report. A switch away from a Big-4 firm mid-decline is a recognised pre-distress red flag.</div></div>` : ""}

    <h2>Key financials</h2>
    <div class="card" style="overflow-x:auto">${financials()}</div>

    ${llmHTML}

    <div class="note" style="margin-top:26px">Scores are decision-support signals from public filings, not a determination of fraud. Beneish M &gt; −2.22, Altman Z'' &lt; 1.1, and rising accruals/receivables/leverage indicate elevated manipulation or distress risk.</div>
  `;
}
function pick(i){ sel=i; render(); }
function setTicker(t){ if(!ALL[t]) return; TK=t; DATA=ALL[t]; A=DATA.aspect_labels;
  years=DATA.years; sel=years.length-1;
  try{ history.replaceState(null,"", "?tk="+t); }catch(e){}
  render(); window.scrollTo(0,0); }
function toggleTheme(){ const r=document.documentElement;
  const cur=r.getAttribute("data-theme");
  const next=cur==="dark"?"light":(cur==="light"?"dark":(matchMedia("(prefers-color-scheme:dark)").matches?"light":"dark"));
  r.setAttribute("data-theme",next); }
const _q=new URLSearchParams(location.search).get("tk");
setTicker(_q && ALL[_q] ? _q : TICKERS[0]);
</script>
"""


def _load_all(tickers=None):
    tickers = tickers or sorted(d for d in os.listdir(OUT)
                                if os.path.isfile(os.path.join(OUT, d, "scores.json")))
    data = {}
    for t in tickers:
        try:
            data[t] = json.load(open(os.path.join(OUT, t, "scores.json"), encoding="utf-8"))
        except Exception:
            continue
    # order by latest overall score desc so the riskiest is first
    return dict(sorted(data.items(),
                       key=lambda kv: -((kv[1].get("years") or [{}])[-1].get("overall_score") or 0)))


def build_combined(tickers=None):
    """One self-contained dashboard embedding every ticker, with a switcher."""
    data = _load_all(tickers)
    if not data:
        return None
    html = TEMPLATE.replace("__ALLDATA__", json.dumps(data, ensure_ascii=False))
    os.makedirs(DASH, exist_ok=True)
    path = os.path.join(DASH, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"wrote {path}  ({', '.join(data)})")
    return path


def build(ticker=None):
    """Back-compat: any single-ticker build now (re)builds the combined page."""
    return build_combined()


def main(argv):
    build_combined(argv[1:] or None)


if __name__ == "__main__":
    main(sys.argv)
