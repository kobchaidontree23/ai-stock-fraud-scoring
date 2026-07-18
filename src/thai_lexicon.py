"""Thai -> canonical line-item lexicon for Thai (SET/SEC) financial statements.

Labels in the source .XLS are stored in TIS-620 and recovered with
`raw.encode('latin1').decode('tis-620')`.  Each canonical field maps to an
ordered list of matcher rules; the first row whose (whitespace-collapsed) label
satisfies a rule wins.

Rule syntax (tuple of (mode, text)):
    ("eq",  s)  -> label == s                (exact, after collapsing spaces)
    ("in",  s)  -> s in label                (substring)
    ("sw",  s)  -> label.startswith(s)

`SUM_FIELDS` are computed by summing every row matching any of the given
startswith prefixes within a statement, minus explicit exclusions.
"""

# --- single-row fields -------------------------------------------------------
FIELD_RULES = {
    # Balance sheet ----------------------------------------------------------
    "cash":                 [("in", "เงินสดและรายการเทียบเท่าเงินสด")],
    "receivables":          [("in", "ลูกหนี้การค้าและลูกหนี้อื่น"),
                             ("in", "ลูกหนี้การค้า")],
    "inventory":            [("eq", "สินค้าคงเหลือ")],
    "current_assets":       [("eq", "รวมสินทรัพย์หมุนเวียน")],
    "ppe":                  [("in", "ที่ดิน อาคารและอุปกรณ์"),
                             ("in", "ที่ดินอาคารและอุปกรณ์"),
                             ("in", "อาคารและอุปกรณ์")],
    "intangibles_rights":   [("in", "ลิขสิทธิ์รายการ")],
    "noncurrent_assets":    [("eq", "รวมสินทรัพย์ไม่หมุนเวียน")],
    "total_assets":         [("eq", "รวมสินทรัพย์")],
    "current_liabilities":  [("eq", "รวมหนี้สินหมุนเวียน")],
    "noncurrent_liabilities": [("eq", "รวมหนี้สินไม่หมุนเวียน")],
    "total_liabilities":    [("eq", "รวมหนี้สิน")],
    "retained_earnings":    [("in", "ยังไม่ได้จัดสรร")],
    "total_equity":         [("eq", "รวมส่วนของผู้ถือหุ้น"),
                             ("in", "รวมส่วนของผู้ถือหุ้น")],

    # Income statement -------------------------------------------------------
    "revenue":              [("eq", "รวมรายได้")],
    "total_expenses":       [("eq", "รวมค่าใช้จ่าย")],
    "sga_selling":          [("in", "ค่าใช้จ่ายในการขาย")],
    "sga_admin":            [("in", "ค่าใช้จ่ายในการบริหาร")],
    "operating_income":     [("in", "กำไรจากการดำเนินงาน")],
    "finance_cost":         [("eq", "ต้นทุนทางการเงิน")],
    "pretax_income":        [("in", "กำไรก่อนค่าใช้จ่ายภาษีเงินได้"),
                             ("in", "กำไรก่อนภาษี"),
                             ("in", "กำไรก่อนภาษีเงินได้"),
                             ("in", "กำไรก่อนรายได้"),        # "…ก่อนรายได้ (ค่าใช้จ่าย) ภาษีเงินได้"
                             ("in", "ก่อนค่าใช้จ่ายภาษีเงินได้"),  # STARK: "กำไร (ขาดทุน) ก่อน…"
                             ("in", "ก่อนภาษีเงินได้")],
    "net_income":           [("eq", "กำไรสำหรับปี"),
                             ("in", "กำไร (ขาดทุน) สำหรับปี"),
                             ("in", "สุทธิสำหรับปี"),           # STARK: "กำไร (ขาดทุน) สุทธิสำหรับปี"
                             ("in", "เบ็ดเสร็จรวมสำหรับปี")],   # last resort (MORE): total comprehensive ≈ net
    "net_income_parent":    [("in", "ส่วนที่เป็นของผู้ถือหุ้นของบริษัท")],
    "bargain_purchase_gain":[("in", "ซื้อกิจการในราคาต่ำกว่ามูลค่ายุติธรรม")],

    # Cash-flow statement ----------------------------------------------------
    "depreciation":         [("eq", "ค่าเสื่อมราคา")],
    "amortization":         [("eq", "ค่าตัดจำหน่าย")],
    # regex tolerates the "(ใช้ไปใน)" insert seen in STARK and negative-CFO filers
    "cfo":                  [("re", r"เงินสดสุทธิ.*กิจกรรมดำเนินงาน"),
                             ("in", "เงินสดสุทธิได้มาจากกิจกรรมดำเนินงาน"),
                             ("in", "เงินสดสุทธิจากกิจกรรมดำเนินงาน")],
    "capex_content":        [("in", "ซื้อสิทธิรายการ"),
                             ("in", "จ่ายล่วงหน้าค่าซื้อสิทธิ")],
}

# --- summed fields ----------------------------------------------------------
# cost of sales = every expense line starting with "ต้นทุน" EXCEPT finance cost
SUM_FIELDS = {
    "cogs": {
        "startswith": ["ต้นทุน"],
        "exclude_in": ["ทางการเงิน"],   # ต้นทุนทางการเงิน is interest, not COGS
        "statement": "income",
    },
}

# which statement section each field is valid in (prevents cross-statement
# label collisions, e.g. the cash-flow working-capital row also named
# "ลูกหนี้การค้าและลูกหนี้อื่น" must not overwrite the balance-sheet receivable).
FIELD_STATEMENT = {
    # balance sheet
    "cash": "balance", "receivables": "balance", "inventory": "balance",
    "current_assets": "balance", "ppe": "balance", "intangibles_rights": "balance",
    "noncurrent_assets": "balance", "total_assets": "balance",
    "current_liabilities": "balance", "noncurrent_liabilities": "balance",
    "total_liabilities": "balance", "retained_earnings": "balance",
    "total_equity": "balance",
    # income statement
    "revenue": "income", "total_expenses": "income", "sga_selling": "income",
    "sga_admin": "income", "operating_income": "income", "finance_cost": "income",
    "pretax_income": "income", "net_income": "income",
    "net_income_parent": "income", "bargain_purchase_gain": "income",
    # cash flow
    "depreciation": "cashflow", "amortization": "cashflow", "cfo": "cashflow",
    "capex_content": "cashflow",
}

# statement identification by title keyword (matched against sheet titles AND
# against in-sheet header rows, since older files title statements inside cells)
STATEMENT_KEYS = {
    "balance": ["งบแสดงฐานะการเงิน", "งบดุล"],
    "income":  ["งบกำไรขาดทุน", "งบกำไร"],
    # NB: require the full phrase, not bare "เปลี่ยนแปลง" — that word also
    # appears in the cash-flow line "profit before CHANGES in operating assets",
    # which would otherwise flip the section mid cash-flow sheet and drop CFO.
    "equity":  ["เปลี่ยนแปลงส่วนของผู้ถือหุ้น"],
    # NB: not bare "กระแสเงินสด" — the net-operating-cash DATA line can start with
    # it (MORE: "กระแสเงินสดสุทธิได้มาจาก (ใช้ไปใน) กิจกรรมดำเนินงาน") and would be
    # mistaken for a section header and skipped. Match the actual headers only.
    "cashflow":["งบกระแสเงินสด", "กระแสเงินสดจากกิจกรรม"],
}

# company / period markers
COMPANY_MARKER = "บริษัท"
CONSOLIDATED_MARKER = "งบการเงินรวม"     # vs เฉพาะกิจการ (separate)
