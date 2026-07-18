"""End-to-end fraud-risk scoring pipeline (generalizable across tickers).

Layout expected:
    data/<TICKER>/financial statement/<TICKER><BEYEAR>/FINANCIAL_STATEMENTS.XLS
    data/<TICKER>/financial statement/<TICKER><BEYEAR>/AUDITOR_REPORT.(doc|docx)
    data/<TICKER>/financial statement/<TICKER><BEYEAR>/NOTES.(doc|docx)
    data/<TICKER>/one report/...                      (optional PDFs)

For each ticker it:
    1. extracts the consolidated financial series (all years found),
    2. computes deterministic forensic metrics + per-aspect risk scores,
    3. extracts qualitative auditor/notes signals per year,
    4. (if credentials available) LLM-scores each year on top of the metrics,
    5. writes output/<TICKER>/scores.json for the dashboard.

Usage:  python src/pipeline.py [TICKER ...]   (default: all tickers under data/)
"""
from __future__ import annotations
import os
import re
import sys
import glob
import json
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract.financials import extract_financials              # noqa: E402
from extract.documents import extract_documents                # noqa: E402
from metrics.forensic import compute_all, ASPECT_LABELS        # noqa: E402
from scoring import llm_scorer                                 # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "output")


def _year_of(path):
    """Buddhist-era year from a folder named with either a BE (25xx) or CE
    (20xx) year — e.g. 'JKN2565' -> 2565, 'MORE 2017' -> 2560 (2017+543)."""
    m = re.search(r"(?<!\d)(\d{4})(?!\d)", os.path.basename(os.path.dirname(path)))
    if not m:
        return None
    y = int(m.group(1))
    if 2500 <= y <= 2599:
        return y
    if 2000 <= y <= 2099:
        return y + 543
    return None


def build_financials(ticker_dir):
    """Merge current+prior consolidated figures across all XLS files."""
    # accept either "financial statement" or "financial report" folder naming,
    # and .xls / .xlsx; one-report folders never hold FINANCIAL_STATEMENTS.*
    files = sorted(f for f in glob.glob(os.path.join(
        ticker_dir, "*", "*", "FINANCIAL_STATEMENTS.*"))
        if f.lower().endswith((".xls", ".xlsx")))
    current, prior = {}, {}
    for f in files:
        y = _year_of(f)
        if not y:
            continue
        d = extract_financials(f, y)
        current[y] = d.get(y, {})
        prior[y - 1] = d.get(y - 1, {})
    fin = {}
    for y in sorted(set(current) | set(prior)):
        merged = dict(prior.get(y, {}))       # prior-year column (fallback)
        merged.update(current.get(y, {}))     # audited current-year column wins
        fin[y] = merged
    return fin


def score_ticker(ticker, fin, docs, use_llm=True, meta=None):
    """Score a ticker from already-extracted financials + documents.

    Data-source-agnostic core shared by the local-file CLI and the SEC-API /
    web-app paths.  `fin` is {year_be: {field: value}}, `docs` is
    {year_be: {auditor, related_party, one_report}}. Returns the result dict
    and writes output/<TICKER>/scores.json.
    """
    if not fin:
        return None
    docs = docs or {}
    metrics = compute_all(fin, docs)

    years_out = []
    llm_status = "not_run"
    for y in sorted(metrics):                 # metrics exist only where prior year present
        m = metrics[y]
        doc = docs.get(y, {})
        quant = m.get("quant_composite")

        llm = {"available": False, "reason": "llm disabled"}
        if use_llm:
            evidence = llm_scorer.build_evidence(ticker, y, fin[y], m, doc)
            llm = llm_scorer.score_year(evidence)
            llm_status = "ok" if llm.get("available") else llm.get("reason", "unavailable")

        if llm.get("available"):
            overall = llm["overall_fraud_risk_score"]
            overall_band = llm["risk_band"]
        else:
            overall = quant
            overall_band = m.get("quant_band")

        years_out.append({
            "year_be": y,
            "year_ce": y - 543,
            "financials": fin[y],
            "aspects": m["aspects"],
            "quant_composite": quant,
            "quant_band": m.get("quant_band"),
            "quant_mean": m.get("quant_mean"),
            "quant_severity": m.get("quant_severity"),
            "documents": {
                "auditor": doc.get("auditor", {"available": False}),
                "related_party": doc.get("related_party", {"available": False}),
                "one_report": {k: v for k, v in doc.get("one_report", {}).items()
                               if k != "text"},   # keep JSON lean; text -> LLM only
            },
            "llm": llm,
            "overall_score": overall,
            "overall_band": overall_band,
        })

    result = {
        "ticker": ticker,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "currency": "THB",
        "year_basis": "Buddhist Era (BE = CE + 543)",
        "aspect_labels": ASPECT_LABELS,
        "llm_status": llm_status,
        "years": years_out,
    }
    if meta:
        result.update(meta)
    out_dir = os.path.join(OUT, ticker)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "scores.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"[{ticker}] wrote {out_dir}/scores.json  "
          f"({len(years_out)} years, llm={llm_status})")
    return result


def run_ticker(ticker, use_llm=True, use_one_report=True):
    """Local-file source: extract from data/<TICKER>/ then score."""
    ticker_dir = os.path.join(DATA, ticker)
    fin = build_financials(ticker_dir)
    if not fin:
        print(f"[{ticker}] no financial data found", file=sys.stderr)
        return None
    docs = extract_documents(ticker_dir, sorted(fin),
                             with_one_report=use_one_report)
    return score_ticker(ticker, fin, docs, use_llm=use_llm,
                        meta={"source": "local_files"})


def main(argv):
    tickers = argv[1:]
    use_llm = os.environ.get("SKIP_LLM") != "1"
    use_or = os.environ.get("SKIP_ONE_REPORT") != "1"
    if not tickers:
        tickers = [d for d in os.listdir(DATA)
                   if os.path.isdir(os.path.join(DATA, d))]
    for t in tickers:
        run_ticker(t, use_llm=use_llm, use_one_report=use_or)


if __name__ == "__main__":
    main(sys.argv)
