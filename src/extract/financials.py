"""Extract canonical financial line items from Thai SET/SEC .XLS statements.

Handles both file layouts seen in practice:
  * newer files: one sheet per statement, Thai sheet titles
  * older files: English sheet codes ("BS", "pl&cf") with several statements
    stacked in one sheet and Thai titles living inside the cells

Strategy:
  * recover TIS-620 labels (mojibake fix)
  * within every sheet, walk rows top-to-bottom; a row whose label contains a
    statement-title keyword switches the "current section" (balance/income/
    cashflow).  Each field is only matched inside its own section, so identical
    Thai labels in different statements never collide.
  * value columns are detected dynamically; the leftmost pair is the
    CONSOLIDATED (current, prior) figures.
  * the reporting (current) Buddhist year comes from the folder name, prior =
    year-1 -- far more reliable than parsing in-sheet period headers.

Public entry point:
    extract_financials(xls_path, report_year) -> {year:int -> {field->value}}
"""
from __future__ import annotations
import re
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from thai_lexicon import (  # noqa: E402
    FIELD_RULES, SUM_FIELDS, STATEMENT_KEYS, FIELD_STATEMENT,
)

_WS = re.compile(r"\s+")


def _fix(s):
    """Recover Thai text mangled by xlrd's default codepage."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin1").decode("tis-620")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _norm(s) -> str:
    f = _fix(s)
    return _WS.sub(" ", f.strip()) if isinstance(f, str) else ""


def _section_of(label: str) -> str | None:
    """If a label is a statement title, return which section it opens."""
    for kind, keys in STATEMENT_KEYS.items():
        if kind == "equity":
            if any(k in label for k in keys):
                return "equity"
            continue
        if any(k in label for k in keys):
            return kind
    return None


def _row_label(df: pd.DataFrame, r: int, max_label_col: int = 6) -> str:
    for c in range(min(max_label_col, df.shape[1])):
        v = _norm(df.iat[r, c])
        if v:
            return v
    return ""


def _value_columns(df: pd.DataFrame):
    """Column indices carrying monetary amounts, left-to-right."""
    counts = {}
    for c in range(df.shape[1]):
        n = 0
        for r in range(df.shape[0]):
            v = df.iat[r, c]
            if isinstance(v, (int, float)) and pd.notna(v) and abs(v) > 1000 \
               and not (2400 < abs(v) < 2600):        # skip Buddhist-year cells
                n += 1
        counts[c] = n
    thresh = max(5, int(0.12 * df.shape[0]))
    return sorted(c for c, n in counts.items() if n >= thresh)


def _match(label: str, rules) -> bool:
    for mode, text in rules:
        if mode == "eq" and label == text:
            return True
        if mode == "in" and text in label:
            return True
        if mode == "sw" and label.startswith(text):
            return True
        if mode == "re" and re.search(text, label):
            return True
    return False


def _num(v):
    return float(v) if isinstance(v, (int, float)) and pd.notna(v) else None


def _extract_sheet(df: pd.DataFrame, cur_col: int, prv_col: int):
    """Return (cur, prv) dicts, section-aware, for one sheet."""
    cur, prv = {}, {}
    section = None

    # sum accumulators for SUM_FIELDS, per section
    sums = {f: {"c": 0.0, "p": 0.0, "hit": False} for f in SUM_FIELDS}

    for r in range(df.shape[0]):
        label = _row_label(df, r)
        if not label:
            continue
        sec = _section_of(label)
        if sec:
            section = sec
            continue
        if section is None:
            continue

        cv, pv = _num(df.iat[r, cur_col]), _num(df.iat[r, prv_col])

        # single-row fields belonging to this section
        for field, rules in FIELD_RULES.items():
            if field in cur:
                continue
            if FIELD_STATEMENT.get(field) != section:
                continue
            if _match(label, rules):
                if cv is not None:
                    cur[field] = cv
                if pv is not None:
                    prv[field] = pv

        # summed fields
        for field, spec in SUM_FIELDS.items():
            if spec.get("statement") != section:
                continue
            if any(label.startswith(p) for p in spec.get("startswith", [])) \
               and not any(e in label for e in spec.get("exclude_in", [])):
                if cv is not None:
                    sums[field]["c"] += cv; sums[field]["hit"] = True
                if pv is not None:
                    sums[field]["p"] += pv

    for field, acc in sums.items():
        if acc["hit"]:
            cur[field] = acc["c"]
            prv[field] = acc["p"]
    return cur, prv


def _year_from_path(path: str):
    m = re.search(r"(25\d\d)", os.path.basename(os.path.dirname(path)))
    return int(m.group(1)) if m else None


def extract_financials(xls_path: str, report_year: int | None = None):
    """Merge current+prior consolidated figures across all statement sheets."""
    if report_year is None:
        report_year = _year_from_path(xls_path)
    xl = pd.ExcelFile(xls_path)
    cur_all, prv_all = {}, {}

    for raw_name in xl.sheet_names:
        df = xl.parse(raw_name, header=None)
        if df.empty:
            continue
        vcols = _value_columns(df)
        if len(vcols) < 2:
            continue
        cur_col, prv_col = vcols[0], vcols[1]      # leftmost pair = consolidated
        cur, prv = _extract_sheet(df, cur_col, prv_col)
        for k, v in cur.items():
            cur_all.setdefault(k, v)
        for k, v in prv.items():
            prv_all.setdefault(k, v)

    out = {}
    if report_year:
        out[report_year] = cur_all
        out[report_year - 1] = prv_all
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(extract_financials(sys.argv[1]), ensure_ascii=False, indent=2))
