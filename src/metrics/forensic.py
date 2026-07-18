"""Deterministic forensic-accounting metrics + per-aspect risk sub-scores.

Every aspect returns a transparent 0-100 risk score (higher = more
fraud/anomaly risk) derived from published academic thresholds, so the LLM
layer scores *on top of* auditable numbers rather than eyeballing them.

Aspects produced per year (where inputs exist):
    beneish     earnings manipulation (Beneish M-Score, 8 vars)
    altman      financial distress (Altman Z''-Score, emerging-market form)
    accruals    accruals / cash-earnings quality (Sloan TATA, CFO vs NI)
    receivables receivable & revenue quality (DSO level + growth divergence)
    leverage    leverage & liquidity (D/E, current ratio, interest coverage)
    piotroski   fundamental health (Piotroski F-Score, invertible to risk)
    oneoff      reliance on non-recurring / non-cash income
    intangible  asset/intangible intensity (content-rights model strain)
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _g(d, k):
    v = d.get(k)
    return float(v) if isinstance(v, (int, float)) else None


def _safe(n, dnm):
    if n is None or dnm in (None, 0):
        return None
    return n / dnm


def _lin(x, pts):
    """Piecewise-linear map; pts = sorted [(x0,y0),...]. Clamped at ends."""
    if x is None:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0) if x1 != x0 else 0
            return y0 + t * (y1 - y0)
    return pts[-1][1]


def _band(score):
    if score is None:
        return "n/a"
    return ("low" if score < 30 else "moderate" if score < 50 else
            "elevated" if score < 70 else "high" if score < 85 else "severe")


def _ebit(y):
    oi = _g(y, "operating_income")
    if oi is not None:
        return oi
    pt, fc = _g(y, "pretax_income"), _g(y, "finance_cost")
    if pt is not None and fc is not None:
        return pt + abs(fc)           # add back interest to pre-tax
    return pt


# ---------------------------------------------------------------------------
# Beneish M-Score
# ---------------------------------------------------------------------------
def beneish(cur, prv):
    r = {"available": False}
    rec_t, rec_p = _g(cur, "receivables"), _g(prv, "receivables")
    s_t, s_p = _g(cur, "revenue"), _g(prv, "revenue")
    cogs_t, cogs_p = _g(cur, "cogs"), _g(prv, "cogs")
    ca_t, ca_p = _g(cur, "current_assets"), _g(prv, "current_assets")
    ppe_t, ppe_p = _g(cur, "ppe"), _g(prv, "ppe")
    ta_t, ta_p = _g(cur, "total_assets"), _g(prv, "total_assets")
    dep_t, dep_p = _g(cur, "depreciation"), _g(prv, "depreciation")
    sga_t = (_g(cur, "sga_selling") or 0) + (_g(cur, "sga_admin") or 0)
    sga_p = (_g(prv, "sga_selling") or 0) + (_g(prv, "sga_admin") or 0)
    tl_t, tl_p = _g(cur, "total_liabilities"), _g(prv, "total_liabilities")
    ni_t, cfo_t = _g(cur, "net_income"), _g(cur, "cfo")

    if None in (rec_t, rec_p, s_t, s_p, ta_t, ta_p) or not all([s_t, s_p, ta_t, ta_p]):
        return r
    DSRI = _safe(_safe(rec_t, s_t), _safe(rec_p, s_p))
    gm_t = _safe(s_t - cogs_t, s_t) if cogs_t is not None else None
    gm_p = _safe(s_p - cogs_p, s_p) if cogs_p is not None else None
    GMI = _safe(gm_p, gm_t) if (gm_t and gm_p) else 1.0
    aqi_t = 1 - _safe((ca_t or 0) + (ppe_t or 0), ta_t) if ta_t else None
    aqi_p = 1 - _safe((ca_p or 0) + (ppe_p or 0), ta_p) if ta_p else None
    AQI = _safe(aqi_t, aqi_p) if (aqi_p not in (None, 0)) else 1.0
    SGI = _safe(s_t, s_p)
    if dep_t and dep_p and ppe_t and ppe_p:
        dr_t, dr_p = _safe(dep_t, dep_t + ppe_t), _safe(dep_p, dep_p + ppe_p)
        DEPI = _safe(dr_p, dr_t) if dr_t else 1.0
    else:
        DEPI = 1.0
    SGAI = _safe(_safe(sga_t, s_t), _safe(sga_p, s_p)) if sga_p else 1.0
    LVGI = _safe(_safe(tl_t, ta_t), _safe(tl_p, ta_p)) if (tl_t and tl_p) else 1.0
    TATA = _safe(ni_t - cfo_t, ta_t) if (ni_t is not None and cfo_t is not None) else None
    if TATA is None:
        return r
    for name, v in [("DSRI", DSRI), ("SGI", SGI)]:
        if v is None:
            return r
    M = (-4.84 + 0.92 * DSRI + 0.528 * (GMI or 1) + 0.404 * (AQI or 1)
         + 0.892 * SGI + 0.115 * (DEPI or 1) - 0.172 * (SGAI or 1)
         + 4.679 * TATA - 0.327 * (LVGI or 1))
    score = _lin(M, [(-2.75, 8), (-2.22, 40), (-1.78, 70), (-1.0, 90), (-0.3, 100)])
    r.update(available=True, M=round(M, 3),
             vars={k: round(v, 3) for k, v in
                   dict(DSRI=DSRI, GMI=GMI or 1, AQI=AQI or 1, SGI=SGI,
                        DEPI=DEPI or 1, SGAI=SGAI or 1, LVGI=LVGI or 1,
                        TATA=TATA).items() if v is not None},
             score=round(score, 1), band=_band(score),
             flag=M > -2.22,
             detail=f"M={M:.2f} (>-2.22 signals likely manipulation); "
                    f"DSRI={DSRI:.2f}, SGI={SGI:.2f}, TATA={TATA:.3f}")
    return r


# ---------------------------------------------------------------------------
# Altman Z''-Score (emerging-market / non-manufacturing)
# ---------------------------------------------------------------------------
def altman(y):
    ta = _g(y, "total_assets")
    ca, cl = _g(y, "current_assets"), _g(y, "current_liabilities")
    re, tl, eq = _g(y, "retained_earnings"), _g(y, "total_liabilities"), _g(y, "total_equity")
    ebit = _ebit(y)
    if not ta or None in (ca, cl, re, tl, eq) or ebit is None or tl == 0:
        return {"available": False}
    X1, X2, X3, X4 = (ca - cl) / ta, re / ta, ebit / ta, eq / tl
    Z = 6.56 * X1 + 3.26 * X2 + 6.72 * X3 + 1.05 * X4
    score = _lin(Z, [(-1, 100), (0, 90), (1.1, 60), (2.6, 20), (3.5, 5)])
    zone = "distress" if Z < 1.1 else "grey" if Z < 2.6 else "safe"
    return {"available": True, "Z": round(Z, 2),
            "vars": {k: round(v, 3) for k, v in dict(X1=X1, X2=X2, X3=X3, X4=X4).items()},
            "score": round(score, 1), "band": _band(score), "zone": zone,
            "detail": f"Z''={Z:.2f} ({zone}); WC/TA={X1:.2f}, EBIT/TA={X3:.2f}, "
                      f"Eq/Liab={X4:.2f}"}


# ---------------------------------------------------------------------------
# Accruals / cash-earnings quality
# ---------------------------------------------------------------------------
def accruals(cur, prv):
    ni, cfo = _g(cur, "net_income"), _g(cur, "cfo")
    ta_t, ta_p = _g(cur, "total_assets"), _g(prv, "total_assets")
    if ni is None or cfo is None or not ta_t:
        return {"available": False}
    avg_ta = ((ta_t + ta_p) / 2) if ta_p else ta_t
    tata = (ni - cfo) / avg_ta
    cfo_ni = _safe(cfo, ni) if ni else None
    # positive accruals (income above cash) are the risky direction
    s1 = _lin(tata, [(-0.05, 10), (0, 25), (0.05, 45), (0.1, 65), (0.2, 90), (0.35, 100)])
    s2 = _lin(cfo_ni, [(0.2, 100), (0.6, 75), (1.0, 45), (1.5, 20), (3, 10)]) if cfo_ni is not None else s1
    score = round(0.6 * s1 + 0.4 * s2, 1)
    return {"available": True, "TATA": round(tata, 3),
            "CFO_to_NI": round(cfo_ni, 2) if cfo_ni is not None else None,
            "score": score, "band": _band(score),
            "detail": f"accruals/assets={tata:.3f}; CFO/NI="
                      f"{cfo_ni:.2f}" if cfo_ni is not None else f"accruals/assets={tata:.3f}"}


# ---------------------------------------------------------------------------
# Receivables & revenue quality
# ---------------------------------------------------------------------------
def receivables(cur, prv):
    rec_t, s_t = _g(cur, "receivables"), _g(cur, "revenue")
    rec_p, s_p = _g(prv, "receivables"), _g(prv, "revenue")
    if not s_t or rec_t is None:
        return {"available": False}
    dso_t = rec_t / s_t * 365
    dso_p = (rec_p / s_p * 365) if (rec_p is not None and s_p) else None
    rec_g = _safe(rec_t - rec_p, rec_p) if rec_p else None
    rev_g = _safe(s_t - s_p, s_p) if s_p else None
    diverge = (rec_g - rev_g) if (rec_g is not None and rev_g is not None) else None
    s_level = _lin(dso_t, [(45, 10), (90, 30), (150, 55), (220, 78), (330, 95), (400, 100)])
    s_div = _lin(diverge, [(-0.1, 10), (0, 30), (0.15, 55), (0.4, 80), (0.8, 100)]) \
        if diverge is not None else s_level
    score = round(0.65 * s_level + 0.35 * s_div, 1)
    return {"available": True, "DSO_days": round(dso_t, 0),
            "DSO_prev": round(dso_p, 0) if dso_p else None,
            "recv_growth": round(rec_g, 3) if rec_g is not None else None,
            "rev_growth": round(rev_g, 3) if rev_g is not None else None,
            "score": score, "band": _band(score),
            "detail": f"DSO={dso_t:.0f}d" + (f" vs {dso_p:.0f}d prior" if dso_p else "")
            + (f"; receivables grew {rec_g*100:.0f}% vs revenue {rev_g*100:.0f}%"
               if (rec_g is not None and rev_g is not None) else "")}


# ---------------------------------------------------------------------------
# Leverage & liquidity
# ---------------------------------------------------------------------------
def leverage(y):
    tl, eq = _g(y, "total_liabilities"), _g(y, "total_equity")
    ca, cl = _g(y, "current_assets"), _g(y, "current_liabilities")
    ebit, fc = _ebit(y), _g(y, "finance_cost")
    de = _safe(tl, eq)
    cr = _safe(ca, cl)
    icov = _safe(ebit, abs(fc)) if (ebit is not None and fc) else None
    if de is None:
        return {"available": False}
    s_de = _lin(de, [(0.3, 10), (1.0, 35), (1.8, 65), (2.5, 85), (4, 100)])
    s_cr = _lin(cr, [(0.5, 100), (0.8, 80), (1.0, 60), (1.5, 30), (2.5, 10)]) if cr else s_de
    s_ic = _lin(icov, [(0.8, 100), (1.5, 80), (3, 50), (6, 25), (12, 10)]) if icov else None
    parts = [s_de, s_cr] + ([s_ic] if s_ic is not None else [])
    score = round(sum(parts) / len(parts), 1)
    return {"available": True, "debt_to_equity": round(de, 2),
            "current_ratio": round(cr, 2) if cr else None,
            "interest_coverage": round(icov, 2) if icov is not None else None,
            "score": score, "band": _band(score),
            "detail": f"D/E={de:.2f}" + (f", current ratio={cr:.2f}" if cr else "")
            + (f", interest cover={icov:.1f}x" if icov is not None else "")}


# ---------------------------------------------------------------------------
# Piotroski F-Score (8 computable components; higher F = healthier)
# ---------------------------------------------------------------------------
def piotroski(cur, prv):
    ni, cfo = _g(cur, "net_income"), _g(cur, "cfo")
    ta_t, ta_p = _g(cur, "total_assets"), _g(prv, "total_assets")
    ni_p, cfo_p = _g(prv, "net_income"), _g(prv, "cfo")
    s_t, s_p = _g(cur, "revenue"), _g(prv, "revenue")
    cogs_t, cogs_p = _g(cur, "cogs"), _g(prv, "cogs")
    cl_t, cl_p = _g(cur, "current_liabilities"), _g(prv, "current_liabilities")
    ca_t, ca_p = _g(cur, "current_assets"), _g(prv, "current_assets")
    ncl_t = _g(cur, "noncurrent_liabilities")
    ncl_p = _g(prv, "noncurrent_liabilities")
    if None in (ni, cfo, ta_t, ta_p) or not ta_t or not ta_p:
        return {"available": False}
    roa_t, roa_p = ni / ta_t, (_safe(ni_p, ta_p) if ni_p is not None else None)
    F, comp = 0, {}
    comp["ROA>0"] = int(roa_t > 0); F += comp["ROA>0"]
    comp["CFO>0"] = int(cfo > 0); F += comp["CFO>0"]
    comp["dROA>0"] = int(roa_p is not None and roa_t > roa_p); F += comp["dROA>0"]
    comp["CFO>NI"] = int(cfo > ni); F += comp["CFO>NI"]
    if ncl_t is not None and ncl_p is not None:
        comp["dLever_down"] = int(_safe(ncl_t, ta_t) <= _safe(ncl_p, ta_p)); F += comp["dLever_down"]
    if ca_t and cl_t and ca_p and cl_p:
        comp["dCurrent_up"] = int(_safe(ca_t, cl_t) > _safe(ca_p, cl_p)); F += comp["dCurrent_up"]
    if s_t and s_p and cogs_t is not None and cogs_p is not None:
        comp["dMargin_up"] = int((s_t - cogs_t) / s_t > (s_p - cogs_p) / s_p); F += comp["dMargin_up"]
    if s_t and s_p:
        comp["dTurnover_up"] = int((s_t / ta_t) > (s_p / ta_p)); F += comp["dTurnover_up"]
    n = len(comp)
    score = round((1 - F / n) * 100, 1)      # low F => high risk
    return {"available": True, "F": F, "components": n, "detail_components": comp,
            "score": score, "band": _band(score),
            "detail": f"F={F}/{n} healthy checks passed"}


# ---------------------------------------------------------------------------
# Reliance on non-recurring / non-cash income
# ---------------------------------------------------------------------------
def oneoff(y):
    pt = _g(y, "pretax_income")
    bpg = _g(y, "bargain_purchase_gain") or 0
    if pt is None or pt == 0:
        return {"available": False}
    ratio = bpg / pt
    score = _lin(ratio, [(0, 8), (0.1, 35), (0.3, 65), (0.5, 85), (0.8, 100)])
    return {"available": True, "oneoff_to_pretax": round(ratio, 3),
            "bargain_purchase_gain": bpg,
            "score": round(score, 1), "band": _band(score),
            "detail": f"non-recurring gains = {ratio*100:.0f}% of pre-tax profit"}


# ---------------------------------------------------------------------------
# Asset / intangible intensity (content-library model strain)
# ---------------------------------------------------------------------------
def intangible(y):
    ta = _g(y, "total_assets")
    intan = _g(y, "intangibles_rights")
    amort, rev = _g(y, "amortization"), _g(y, "revenue")
    if not ta or intan is None:
        return {"available": False}
    intan_ta = intan / ta
    amort_rev = _safe(amort, rev)
    s1 = _lin(intan_ta, [(0.1, 10), (0.25, 35), (0.4, 60), (0.55, 85), (0.7, 100)])
    s2 = _lin(amort_rev, [(0.05, 10), (0.2, 40), (0.35, 65), (0.5, 90), (0.7, 100)]) \
        if amort_rev is not None else s1
    score = round(0.55 * s1 + 0.45 * s2, 1)
    return {"available": True, "intangibles_to_assets": round(intan_ta, 3),
            "amortization_to_revenue": round(amort_rev, 3) if amort_rev is not None else None,
            "score": score, "band": _band(score),
            "detail": f"intangibles = {intan_ta*100:.0f}% of assets"
            + (f"; amortisation = {amort_rev*100:.0f}% of revenue" if amort_rev is not None else "")}


# ---------------------------------------------------------------------------
# Cash conversion / free-cash-flow quality
# ---------------------------------------------------------------------------
def cash_conversion(cur, prv):
    """Is reported profit backed by cash once library reinvestment is counted?

    Reported operating cash flow can look healthy purely because a large
    non-cash amortization of the content library is added back. The honest
    test subtracts the cash the library actually consumes:

        content reinvestment  = (intangibles_t - intangibles_{t-1}) + amort_t
        free cash flow (FCF)  = CFO - content reinvestment

    Persistently negative FCF while reporting profit and positive CFO -- with
    the gap plugged by rising debt -- is the classic content-licensing failure
    mode (revenue booked, cash never realised, more borrowing to keep buying).
    """
    cfo, ni, rev = _g(cur, "cfo"), _g(cur, "net_income"), _g(cur, "revenue")
    amort = _g(cur, "amortization")
    intan_t, intan_p = _g(cur, "intangibles_rights"), _g(prv, "intangibles_rights")
    if cfo is None or intan_t is None or intan_p is None or amort is None or not rev:
        return {"available": False}
    reinvest = (intan_t - intan_p) + amort
    fcf = cfo - reinvest
    fcf_rev = fcf / rev
    cash_real = _safe(cfo, ni) if ni else None
    score = _lin(fcf_rev, [(-0.6, 100), (-0.3, 88), (-0.1, 68),
                           (0, 45), (0.1, 25), (0.25, 8)])
    return {"available": True,
            "cfo": round(cfo), "content_reinvestment": round(reinvest),
            "free_cash_flow": round(fcf), "net_income": round(ni) if ni else None,
            "fcf_to_revenue": round(fcf_rev, 3),
            "cash_realization_cfo_ni": round(cash_real, 2) if cash_real is not None else None,
            "score": round(score, 1), "band": _band(score),
            "detail": f"free cash flow = {fcf/1e6:,.0f}M ({fcf_rev*100:.0f}% of revenue) "
                      f"after {reinvest/1e6:,.0f}M content reinvestment; "
                      f"reported CFO/NI = {cash_real:.1f}x looks healthy only via "
                      f"non-cash amortisation add-back" if cash_real is not None else
                      f"free cash flow = {fcf/1e6:,.0f}M ({fcf_rev*100:.0f}% of revenue)"}


# ---------------------------------------------------------------------------
# Governance & disclosure (from auditor report + One Report / 56-1)
# ---------------------------------------------------------------------------
def governance(doc, prv_doc):
    """Score audit/governance quality: opinion severity, auditor rotation
    (especially a Big-4 -> small-firm downgrade), and related-party growth.

    Auditor changes mid-decline are a recognised pre-distress red flag; this is
    the signal the financial statements themselves cannot show.
    """
    if not doc:
        return {"available": False}
    aud = doc.get("auditor", {}) or {}
    rp = doc.get("related_party", {}) or {}
    orp = doc.get("one_report", {}) or {}
    prv_aud = (prv_doc or {}).get("auditor", {}) or {}

    audit_c = aud.get("score") if aud.get("available") else None

    rotation, rot_note = None, None
    if aud.get("available") and prv_aud.get("available") \
       and aud.get("auditor_license") and prv_aud.get("auditor_license"):
        big_now, big_prv = aud.get("auditor_big4"), prv_aud.get("auditor_big4")
        firm_now, firm_prv = aud.get("auditor_firm"), prv_aud.get("auditor_firm")
        if big_prv is True and big_now is False:
            rotation, rot_note = 88, f"auditor downgraded {firm_prv}(Big-4)→{firm_now}"
        elif firm_now and firm_prv and firm_now != firm_prv:
            rotation, rot_note = 66, f"auditor firm changed {firm_prv}→{firm_now}"
        elif aud["auditor_license"] != prv_aud["auditor_license"]:
            rotation, rot_note = 34, "engagement partner rotated"
        else:
            rotation, rot_note = 10, "auditor stable"

    rpt_now = (rp.get("related_party_mentions") or 0) + (orp.get("related_party_mentions") or 0)
    rpt_prv = ((prv_doc or {}).get("related_party", {}).get("related_party_mentions") or 0) \
        + ((prv_doc or {}).get("one_report", {}).get("related_party_mentions") or 0)

    comps = [c for c in (audit_c, rotation) if c is not None]
    if not comps:
        return {"available": False}
    base = sum(comps) / len(comps)
    sev = max(comps)
    score = 0.5 * base + 0.5 * sev
    if rpt_prv and rpt_now / rpt_prv > 1.3:      # related-party disclosures growing fast
        score = min(100, score + 8)
    if aud.get("auditor_big4") is False:         # ongoing non-Big-4 incumbency
        score = max(score, 28)

    detail = f"opinion={aud.get('opinion', 'n/a')}"
    if rot_note:
        detail += f"; {rot_note}"
    detail += f"; related-party refs={rpt_now}"
    return {"available": True, "score": round(score, 1), "band": _band(score),
            "opinion": aud.get("opinion"), "auditor_firm": aud.get("auditor_firm"),
            "auditor_license": aud.get("auditor_license"),
            "auditor_big4": aud.get("auditor_big4"),
            "rotation": rot_note, "related_party_refs": rpt_now,
            "one_report_sources": orp.get("sources") if orp.get("available") else None,
            "detail": detail}


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------
ASPECT_LABELS = {
    "beneish": "Earnings manipulation (Beneish M)",
    "altman": "Financial distress (Altman Z'')",
    "accruals": "Accruals & cash quality",
    "receivables": "Receivable & revenue quality",
    "leverage": "Leverage & liquidity",
    "piotroski": "Fundamental health (Piotroski F)",
    "oneoff": "Non-recurring income reliance",
    "intangible": "Intangible/asset intensity",
    "cash_conversion": "Cash conversion (free cash flow)",
    "governance": "Governance & disclosure",
    "profitability": "Profitability & margins",
}
# weights for the deterministic quantitative composite (sum need not be 1)
ASPECT_WEIGHTS = {
    "beneish": 1.6, "altman": 1.3, "accruals": 1.3, "receivables": 1.5,
    "leverage": 1.1, "piotroski": 0.8, "oneoff": 0.9, "intangible": 1.0,
    "cash_conversion": 1.5, "governance": 1.2, "profitability": 1.0,
}


def compute_year(cur, prv, doc=None, prv_doc=None):
    a = {
        "beneish": beneish(cur, prv),
        "altman": altman(cur),
        "accruals": accruals(cur, prv),
        "receivables": receivables(cur, prv),
        "leverage": leverage(cur),
        "piotroski": piotroski(cur, prv),
        "oneoff": oneoff(cur),
        "intangible": intangible(cur),
        "cash_conversion": cash_conversion(cur, prv),
        "governance": governance(doc, prv_doc),
    }
    num = den = 0.0
    scores = []
    for k, v in a.items():
        if v.get("available") and v.get("score") is not None:
            w = ASPECT_WEIGHTS[k]
            num += w * v["score"]
            den += w
            scores.append(v["score"])
    if not den:
        return {"aspects": a, "quant_composite": None, "quant_band": _band(None)}
    wmean = num / den
    # severity-sensitive: a few severe red flags should dominate a fraud score,
    # so blend the weighted mean with the mean of the worst three aspects.
    topk = sorted(scores, reverse=True)[:3]
    sev = sum(topk) / len(topk)
    composite = round(0.45 * wmean + 0.55 * sev, 1)
    return {"aspects": a, "quant_composite": composite, "quant_band": _band(composite),
            "quant_mean": round(wmean, 1), "quant_severity": round(sev, 1)}


def compute_all(financials: dict, documents: dict | None = None):
    documents = documents or {}
    years = sorted(int(y) for y in financials)
    out = {}
    for y in years:
        prv = financials.get(y - 1) or financials.get(str(y - 1))
        cur = financials.get(y) or financials.get(str(y))
        if prv is None:
            continue
        out[y] = compute_year(cur, prv,
                              documents.get(y), documents.get(y - 1))
    return out
