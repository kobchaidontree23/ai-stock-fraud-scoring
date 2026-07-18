"""Web app: one switchable dashboard for the fraud/anomaly risk of SET tickers.

The home page is a single combined dashboard (all scored tickers, switchable
in-page). A search box scores a new ticker on demand and jumps to it. Source
is chosen automatically: local files under data/<TICKER>/, else the SEC Open
API when SEC_API_KEY is set.

Run:  python webapp/app.py     then open http://127.0.0.1:5000
"""
from __future__ import annotations
import os
import sys
import glob
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from flask import Flask, Response, request, redirect, url_for  # noqa: E402
import pipeline                                                 # noqa: E402
import dashboard                                                # noqa: E402

app = Flask(__name__)
OUT = os.path.join(ROOT, "output")
DATA = os.path.join(ROOT, "data")
DASH = os.path.join(ROOT, "dashboard")

LLM_ON = bool(os.environ.get("ANTHROPIC_API_KEY"))
SEC_ON = bool(os.environ.get("SEC_API_KEY") or os.environ.get("OCP_APIM_SUBSCRIPTION_KEY"))

SEARCH = ('<div style="max-width:1100px;margin:0 auto;padding:22px 20px 0">'
          '<form action="/scan" method="get" style="display:flex;gap:8px">'
          '<input name="ticker" placeholder="Scan another SET ticker (e.g. JKN, STARK, DELTA)…" '
          'style="flex:1;max-width:380px;padding:10px 13px;border:1px solid var(--border);'
          'border-radius:9px;background:var(--card);color:var(--ink);font-size:14px">'
          '<button style="padding:10px 18px;border:0;border-radius:9px;background:var(--accent);'
          'color:#fff;font-weight:600;cursor:pointer">Scan</button></form>'
          '__MSG__</div>')

ANCHOR = '<div class="wrap" id="app"></div>'


def _served_html(msg=""):
    dashboard.build_combined()
    path = os.path.join(DASH, "index.html")
    if not os.path.exists(path):
        return ('<body style="font-family:system-ui;padding:40px">No tickers scored yet. '
                'Add data under <code>data/&lt;TICKER&gt;/</code> or set SEC_API_KEY, then scan one.</body>')
    html = open(path, encoding="utf-8").read()
    m = (f'<div style="margin-top:10px;color:#d03b3b;font-size:13px">{msg}</div>') if msg else ""
    return html.replace(ANCHOR, SEARCH.replace("__MSG__", m) + ANCHOR)


@app.route("/")
def home():
    return Response(_served_html(), mimetype="text/html")


def _score(sym):
    """Score a ticker: local files first, else SEC API. Returns error str or None."""
    if os.path.isdir(os.path.join(DATA, sym)):
        pipeline.run_ticker(sym, use_llm=LLM_ON,
                            use_one_report=os.environ.get("SKIP_ONE_REPORT") != "1")
    elif SEC_ON:
        import sources.sec as sec
        fin, docs, meta = sec.load(sym)
        if not fin:
            return meta.get("error", "no financial data from SEC API")
        pipeline.score_ticker(sym, fin, docs, use_llm=LLM_ON, meta=meta)
    else:
        return (f"No local data for {sym}, and no SEC API key set. Add "
                f"data/{sym}/ or set SEC_API_KEY (SEC One Report covers FY2021+).")
    return None


@app.route("/scan")
def scan():
    sym = (request.args.get("ticker") or "").strip().upper()
    if not sym:
        return redirect(url_for("home"))
    if not os.path.isfile(os.path.join(OUT, sym, "scores.json")) or request.args.get("rescore"):
        try:
            err = _score(sym)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return Response(_served_html(f"Failed to score {sym}: {e}"), mimetype="text/html")
        if err:
            return Response(_served_html(err), mimetype="text/html")
    return redirect(f"/?tk={sym}")


# back-compat: old per-ticker URL -> combined dashboard focused on that ticker
@app.route("/ticker/<sym>")
def ticker(sym):
    return redirect(f"/?tk={sym.strip().upper()}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    scored = sorted(os.path.basename(os.path.dirname(p))
                    for p in glob.glob(os.path.join(OUT, "*", "scores.json")))
    print(f"-> http://127.0.0.1:{port}   tickers: {scored or '(none)'}   "
          f"(sec={'on' if SEC_ON else 'off'}, llm={'on' if LLM_ON else 'off'})")
    app.run(host="127.0.0.1", port=port, debug=False)
