"""LLM fraud-risk scoring via the Anthropic API.

The LLM scores *on top of* the deterministic forensic metrics: it receives the
computed per-aspect scores, the raw financial series, and the qualitative
document signals, and returns qualitative aspect scores (auditor, related
party, revenue recognition, governance) plus a synthesised overall fraud/
anomaly risk score with cited red flags.

Requires an ANTHROPIC_API_KEY (or an `ant auth login` profile). If neither the
`anthropic` package nor credentials are available, `score_year` returns
{"available": False, ...} so the pipeline still emits the deterministic scores.
"""
from __future__ import annotations
import json
import os

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

SYSTEM = """You are a forensic accounting analyst assessing a listed company's \
annual filing for signs of financial statement fraud, earnings manipulation, \
and abnormal financial figures.

You are given, for one fiscal year:
  - the raw consolidated financial line items (in the reporting currency),
  - deterministic forensic metrics already computed (Beneish M-Score, Altman \
Z''-Score, accruals/cash quality, receivable & revenue quality, leverage, \
Piotroski F, non-recurring income reliance, intangible intensity), each with a \
0-100 risk sub-score,
  - qualitative signals extracted from the auditor's report and notes \
(opinion type, going-concern, emphasis-of-matter text, related-party \
prominence).

Reason from this evidence. Do not invent numbers not present in the evidence. \
Higher scores mean higher fraud/anomaly risk. Ground every red flag in a \
specific figure, metric, or auditor statement from the evidence. Be calibrated: \
a clean, unremarkable year should score low; converging severe signals should \
score high."""

# Structured-output schema (json_schema). Keep to supported keywords only:
# no minLength/maximum/etc. — enums and additionalProperties:false are fine.
_ASPECT = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "rationale": {"type": "string"},
    },
    "required": ["score", "rationale"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "overall_fraud_risk_score": {"type": "integer"},
        "risk_band": {"type": "string",
                      "enum": ["low", "moderate", "elevated", "high", "severe"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "qualitative_aspects": {
            "type": "object",
            "properties": {
                "auditor_signals": _ASPECT,
                "related_party": _ASPECT,
                "revenue_recognition": _ASPECT,
                "governance_disclosure": _ASPECT,
            },
            "required": ["auditor_signals", "related_party",
                         "revenue_recognition", "governance_disclosure"],
            "additionalProperties": False,
        },
        "top_red_flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "severity": {"type": "string",
                                 "enum": ["low", "moderate", "high", "severe"]},
                    "evidence": {"type": "string"},
                },
                "required": ["title", "severity", "evidence"],
                "additionalProperties": False,
            },
        },
        "narrative": {"type": "string"},
    },
    "required": ["overall_fraud_risk_score", "risk_band", "confidence",
                 "qualitative_aspects", "top_red_flags", "narrative"],
    "additionalProperties": False,
}


def build_evidence(ticker, year, financials, metrics, documents):
    """Assemble a compact, LLM-ready evidence package for one year."""
    m = metrics or {}
    aspects = {k: {kk: vv for kk, vv in v.items()
                   if kk in ("score", "band", "M", "Z", "DSO_days", "TATA",
                             "CFO_to_NI", "debt_to_equity", "current_ratio",
                             "interest_coverage", "F", "oneoff_to_pretax",
                             "intangibles_to_assets", "detail")}
               for k, v in (m.get("aspects") or {}).items() if v.get("available")}
    doc = documents or {}
    aud = doc.get("auditor", {})
    rp = doc.get("related_party", {})
    orp = doc.get("one_report", {})
    return {
        "ticker": ticker,
        "fiscal_year_buddhist": year,
        "fiscal_year_gregorian": year - 543,
        "financials": {k: financials.get(k) for k in sorted(financials)},
        "deterministic_metrics": aspects,
        "deterministic_quant_composite": m.get("quant_composite"),
        "auditor_signals": {k: aud.get(k) for k in
                            ("opinion", "going_concern", "emphasis_of_matter",
                             "has_kam", "emphasis_text", "going_concern_text",
                             "auditor_firm", "auditor_license", "auditor_big4")
                            if aud.get("available")},
        "related_party_note_mentions": rp.get("related_party_mentions"),
        "one_report_excerpt": (orp.get("text", "")[:9000]
                               if orp.get("available") else None),
        "one_report_sources": orp.get("sources") if orp.get("available") else None,
    }


def score_year(evidence: dict, model: str = MODEL) -> dict:
    try:
        import anthropic
    except ImportError:
        return {"available": False, "reason": "anthropic package not installed"}
    try:
        client = anthropic.Anthropic()
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": f"client init failed: {e}"}

    user = ("Assess the following annual-filing evidence and return the "
            "structured fraud/anomaly risk assessment.\n\n"
            + json.dumps(evidence, ensure_ascii=False, indent=2))
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=8000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "high",
                           "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": f"api error: {e}"}

    if resp.stop_reason == "refusal":
        return {"available": False, "reason": "model refused",
                "details": getattr(resp, "stop_details", None)}
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"available": False, "reason": "non-JSON response", "raw": text[:500]}
    data["available"] = True
    data["model"] = resp.model
    return data
