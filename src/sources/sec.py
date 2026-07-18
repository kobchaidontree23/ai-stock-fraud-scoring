"""SEC Open API (Thailand) data source — automated pull for any SET ticker.

Uses the Form 56-1 One Report dataset:
  * /v1/one-report/sbo/{year}/info/{lang}                      -> company list (ticker -> unique_id)
  * /v1/one-report/fs/{year}/financial_statement/{unique_id}   -> statements + ratios
  * /v1/one-report/cgs/{year}/auditor_company/{unique_id}      -> auditor firm
  * /v1/one-report/cgp/{year}/governance/{unique_id}           -> governance narrative

DATA CONSTRAINT: the One Report format began with fiscal year 2564 (2021), so
this source only covers ~2021 onward (typically 3-4 years) — enough for Beneish
(2 consecutive years) and short trends, but not a long history.

The HTTP client, ticker resolver, and fetch/probe helpers are complete. The
field-name mappers (`map_financial_statement`, `map_auditor`) are keyed on
best-guess field names and are finalised against a live payload via the `probe`
CLI once a subscription key is available:

    SEC_API_KEY=xxxx python -m sources.sec resolve JKN
    SEC_API_KEY=xxxx python -m sources.sec probe-fs <unique_id> 2565
"""
from __future__ import annotations
import os
import sys
import time
import json

BASE = "https://api.sec.or.th"
# Candidate report_years to probe (Buddhist Era). One Report starts 2564.
DEFAULT_YEARS = [2567, 2566, 2565, 2564]


def _key(explicit=None):
    k = explicit or os.environ.get("SEC_API_KEY") or os.environ.get("OCP_APIM_SUBSCRIPTION_KEY")
    if not k:
        raise RuntimeError("No SEC API key. Set SEC_API_KEY or pass key=…")
    return k


def _get(path, key=None, params=None, _tries=3):
    import requests
    headers = {"Ocp-Apim-Subscription-Key": _key(key),
               "Content-Type": "application/json"}
    url = BASE + path
    for attempt in range(_tries):
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 421:                       # rate limited
            time.sleep(float(r.headers.get("Retry-After", "2")))
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        time.sleep(0.02)                               # be polite to the API
        try:
            return r.json()
        except ValueError:
            return None
    return None


def _items(resp):
    if resp is None:
        return []
    if isinstance(resp, list):
        return resp
    return resp.get("items") or resp.get("data") or []


# ---------------------------------------------------------------------------
# ticker -> unique_id
# ---------------------------------------------------------------------------
_SYMBOL_FIELDS = ["symbol", "securities_symbol", "ticker", "SecuritiesSymbol",
                  "security_symbol", "stock_symbol"]
_UID_FIELDS = ["unique_id", "uniqueId", "company_id", "companyId", "id"]


def _field(row, names):
    for n in names:
        if isinstance(row, dict) and row.get(n) not in (None, ""):
            return row[n]
    return None


def resolve_unique_id(ticker, key=None, years=DEFAULT_YEARS, lang="E"):
    """Find a company's unique_id from the SET symbol via the sbo/info list."""
    ticker = ticker.strip().upper()
    for y in years:
        resp = _get(f"/v1/one-report/sbo/{y}/info/{lang}", key)
        for row in _items(resp):
            sym = _field(row, _SYMBOL_FIELDS)
            if sym and str(sym).strip().upper() == ticker:
                uid = _field(row, _UID_FIELDS)
                if uid:
                    return {"unique_id": uid, "report_year": y,
                            "name": _field(row, ["company_name", "name_en",
                                                 "name_th", "company_name_en"])}
    return None


def available_years(unique_id, key=None, years=DEFAULT_YEARS):
    """Which report_years actually return a financial statement for this id."""
    out = []
    for y in years:
        fs = _get(f"/v1/one-report/fs/{y}/financial_statement/{unique_id}", key)
        if _items(fs) or fs:
            out.append(y)
    return sorted(out)


# ---------------------------------------------------------------------------
# financial statement -> canonical fields   (FINALISE against a live payload)
# ---------------------------------------------------------------------------
# Maps our canonical field -> candidate SEC field names (Thai/English). These
# are best-guesses; run `probe-fs` with a key and adjust to the real keys.
FS_FIELD_MAP = {
    "revenue":              ["total_revenue", "totalRevenue", "รวมรายได้", "revenue"],
    "cogs":                 ["cost_of_sales", "costOfGoodsSold", "ต้นทุนขาย"],
    "net_income":           ["net_profit", "netProfit", "กำไรสุทธิ", "profit_for_period"],
    "net_income_parent":    ["net_profit_owner", "profit_attributable_to_parent"],
    "receivables":          ["trade_receivable", "tradeReceivables", "ลูกหนี้การค้า"],
    "inventory":            ["inventory", "inventories", "สินค้าคงเหลือ"],
    "current_assets":       ["total_current_assets", "totalCurrentAssets", "รวมสินทรัพย์หมุนเวียน"],
    "total_assets":         ["total_assets", "totalAssets", "รวมสินทรัพย์"],
    "ppe":                  ["ppe", "property_plant_equipment", "ที่ดินอาคารและอุปกรณ์"],
    "intangibles_rights":   ["intangible_assets", "intangibleAssets"],
    "current_liabilities":  ["total_current_liabilities", "totalCurrentLiabilities", "รวมหนี้สินหมุนเวียน"],
    "total_liabilities":    ["total_liabilities", "totalLiabilities", "รวมหนี้สิน"],
    "total_equity":         ["total_equity", "totalEquity", "shareholder_equity", "รวมส่วนของผู้ถือหุ้น"],
    "retained_earnings":    ["retained_earnings", "retainedEarnings", "กำไรสะสม"],
    "operating_income":     ["operating_profit", "operatingProfit", "กำไรจากการดำเนินงาน"],
    "finance_cost":         ["finance_cost", "financeCost", "ต้นทุนทางการเงิน"],
    "pretax_income":        ["profit_before_tax", "profitBeforeTax", "กำไรก่อนภาษี"],
    "cfo":                  ["cash_from_operating", "cashFlowOperating", "net_cash_operating"],
    "amortization":         ["amortization", "amortisation", "depreciation_amortization"],
    "depreciation":         ["depreciation"],
}


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def map_financial_statement(raw):
    """Flatten a fs payload to {canonical_field: value}. Tolerant of shape."""
    # a fs response may be a dict, a list of line-item rows, or nested.
    flat = {}
    rows = _items(raw) if isinstance(raw, dict) and ("items" in raw or "data" in raw) else raw
    if isinstance(rows, dict):
        flat = {k: _num(v) for k, v in rows.items()}
    elif isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                for k, v in row.items():
                    if isinstance(v, (int, float, str)):
                        flat.setdefault(k, _num(v))
    out = {}
    for canon, cands in FS_FIELD_MAP.items():
        for c in cands:
            if c in flat and flat[c] is not None:
                out[canon] = flat[c]
                break
    return out


def map_auditor(raw):
    from extract.documents import _audit_firm    # reuse Big-4 classifier
    text = json.dumps(raw, ensure_ascii=False) if raw else ""
    firm, big4 = _audit_firm(text)
    name = None
    for row in _items(raw) if raw else []:
        name = _field(row, ["auditor_company_name", "audit_firm", "auditorCompany",
                            "company_name", "name"]) or name
    return {"available": bool(firm or name), "opinion": None,
            "emphasis_of_matter": False, "going_concern": False,
            "auditor_firm": firm, "auditor_big4": big4,
            "auditor_license": None, "auditor_company_raw": name, "score": None}


# ---------------------------------------------------------------------------
# high-level load  (used by the pipeline / web app)
# ---------------------------------------------------------------------------
def load(ticker, key=None, years=DEFAULT_YEARS):
    """Return (financials, docs, meta) for a SET ticker from the SEC API."""
    key = _key(key)
    r = resolve_unique_id(ticker, key, years)
    if not r:
        return {}, {}, {"source": "sec_open_api", "error": f"ticker {ticker} not found"}
    uid = r["unique_id"]
    yrs = available_years(uid, key, years)
    fin, docs = {}, {}
    for y in yrs:                                     # y is Buddhist-era report year
        fs = _get(f"/v1/one-report/fs/{y}/financial_statement/{uid}", key)
        fields = map_financial_statement(fs)
        if fields:
            fin[y] = fields
        aud_raw = _get(f"/v1/one-report/cgs/{y}/auditor_company/{uid}", key)
        gov_raw = _get(f"/v1/one-report/cgp/{y}/governance/{uid}", key)
        docs[y] = {"auditor": map_auditor(aud_raw),
                   "related_party": {"available": False},
                   "one_report": {"available": bool(gov_raw),
                                  "text": json.dumps(gov_raw, ensure_ascii=False)[:9000]
                                  if gov_raw else "", "sources": ["cgp/governance"]}}
    meta = {"source": "sec_open_api", "unique_id": uid,
            "company": r.get("name"), "years_available": yrs,
            "data_constraint": "One Report (56-1) covers FY2564/2021 onward only"}
    return fin, docs, meta


# ---------------------------------------------------------------------------
# probe CLI — finalise field mappings against a live key
# ---------------------------------------------------------------------------
def _main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "resolve":
        print(json.dumps(resolve_unique_id(argv[2]), ensure_ascii=False, indent=2))
    elif cmd == "probe-fs":
        uid, y = argv[2], argv[3]
        raw = _get(f"/v1/one-report/fs/{y}/financial_statement/{uid}")
        print(json.dumps(raw, ensure_ascii=False, indent=2)[:6000])
    elif cmd == "years":
        print(available_years(argv[2]))
    elif cmd == "load":
        fin, docs, meta = load(argv[2])
        print(json.dumps({"meta": meta, "years": sorted(fin),
                          "sample_fields": {y: sorted(f) for y, f in fin.items()}},
                         ensure_ascii=False, indent=2))
    else:
        print("usage: python -m sources.sec {resolve TICKER | probe-fs UID YEAR | "
              "years UID | load TICKER}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _main(sys.argv)
