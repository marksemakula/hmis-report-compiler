"""Build the August 2026 "All others" review workbook.

Thirty-one per cent of August's outpatient diagnoses were reported on one line,
105-OP01 "All others", which makes it the largest line on the form. Some of
that is the form's own design and some of it is a decision nobody has made.
Telling those apart is a records-officer's judgement, not a programmer's, so
this writes the question down in a form somebody can answer: every condition
that landed in All others, how often, and what could receive it instead.

    python scripts/build_august_review.py <15_august_reconciliation.xlsx> [out.xlsx]
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from openpyxl import Workbook, load_workbook                       # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill           # noqa: E402
from openpyxl.utils import get_column_letter                       # noqa: E402

from _lib.metadata import mapping                                  # noqa: E402
from _lib.diagnosis_map import map_diagnosis                       # noqa: E402

FONT = "Gill Sans MT"
INK = Font(name=FONT, size=11)
BOLD = Font(name=FONT, size=11, bold=True)
TITLE = Font(name=FONT, size=14, bold=True)
MUTED = Font(name=FONT, size=10, italic=True, color="555555")
FILL_IN = PatternFill("solid", fgColor="FFF3BF")      # cells the reader edits
HEADER = PatternFill("solid", fgColor="E9ECEF")
WRAP = Alignment(vertical="top", wrap_text=True)
TOP = Alignment(vertical="top")

# Where a condition has a home on the current form that the mapping is not yet
# using. Everything else is left blank on purpose: a suggestion nobody checked
# is worse than an empty cell, because it gets accepted.
SUGGESTED = {
    "AA03":      ("EN17", "Other ENT conditions"),
    "DA09.2":    ("OD04", "Other Oral Conditions"),
    "DA09.70":   ("OD04", "Other Oral Conditions"),
    "DA09.7":    ("OD04", "Other Oral Conditions"),
    "DA0Z":      ("OD04", "Other Oral Conditions"),
}

# Why a condition sits in All others, when the reason is known. Written for the
# person deciding, not for the programmer.
NOTE_POLICY = ("Policy. The current form has no OPD line for this; the 2019 "
               "line OT10 is retired. Reported instead on the HIV or TB form.")
NOTE_NO_LINE = "The current form has no line for this condition."

POLICY_WORDS = ("HIV", "IMMUNODEFICIENCY", "RETROVIRAL", "TUBERCULOSIS",
                "PREP", "PEP")


def is_policy(name: str) -> bool:
    upper = name.upper()
    return (any(w in upper for w in POLICY_WORDS[:4])
            or upper.strip() in ("PREP", "PEP"))


def read_codes(path: str):
    """The section-5 rows of the reconciliation grid: code, name, count."""
    rows = [r for r in load_workbook(path, data_only=True).worksheets[0]
            .iter_rows(values_only=True) if str(r[0]) == "5_august_codes"]
    listed, tail = [], 0
    for r in rows:
        code, name, n = str(r[1]).strip(), str(r[2] or "").strip(), int(r[3])
        if code.startswith("(all codes"):
            tail = n
        else:
            listed.append((code, name, n))
    return listed, tail


def widths(ws, spec):
    for col, w in spec.items():
        ws.column_dimensions[col].width = w


def head(ws, row, labels):
    for i, label in enumerate(labels, start=1):
        c = ws.cell(row=row, column=i, value=label)
        c.font, c.fill, c.alignment = BOLD, HEADER, WRAP
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def build(src: str, out: str):
    listed, tail = read_codes(src)
    index = mapping()["HMIS105_01_codeIndex"]
    names = {v["code"]: v["name"] for v in
             mapping()["dataElements"]["HMIS105_01"].values() if v.get("code")}

    totals, others = Counter(), []
    for code, name, n in listed:
        hmis = map_diagnosis(code, index, source="icd11")
        totals[hmis] += n
        if hmis == "OP01":
            others.append((code, name, n))
    others.sort(key=lambda r: -r[2])
    month = sum(n for _, _, n in listed) + tail

    wb = Workbook()

    # ---------------------------------------------------------------- read me
    ws = wb.active
    ws.title = "Read me"
    widths(ws, {"A": 96})
    lines = [
        ("HMIS 105:01, August 2026 - conditions reported as All others", TITLE),
        ("Jinja Regional Referral Hospital", MUTED),
        ("", INK),
        ("August recorded %s outpatient diagnoses. %s of them, %.0f per cent, were "
         "reported on one line, 105-OP01 All others, which makes it the largest "
         "line on the form."
         % (f"{month:,}", f"{totals['OP01'] + tail:,}",
            100 * (totals["OP01"] + tail) / month), INK),
        ("", INK),
        ("Three different things are sitting in that one line and they need "
         "different answers:", BOLD),
        ("", INK),
        ("1. Conditions the form has no line for. Peripheral neuropathy, "
         "sciatica, osteoarthritis and the rest of the musculoskeletal and pain "
         "presentations have nowhere else to go on the current 105:01. All "
         "others is the correct destination and nothing needs to change.", INK),
        ("", INK),
        ("2. HIV and TB. These are a policy decision, not a mapping fault. The "
         "current form carries no OPD diagnosis line for either; the 2019 line "
         "OT10 HIV/AIDS is retired and invisible. They are reported through the "
         "HIV and TB forms instead. Whether their OPD attendance should also "
         "appear here as a diagnosis is for the records officer to settle, and "
         "it is the single largest item in the list.", INK),
        ("", INK),
        ("3. Conditions that do have a home and are not reaching it. These are "
         "few and are marked with a suggestion in column E.", INK),
        ("", INK),
        ("How to use this workbook", BOLD),
        ("Work down the All others sheet. The shaded column F is the only one to "
         "write in. Put the HMIS 105 code the condition should be reported "
         "under, or the word Keep if All others is right. The first row is an "
         "example and can be overwritten.", INK),
        ("", INK),
        ("What this does not cover", BOLD),
        ("%s diagnoses sit in codes used fewer than five times each in August. "
         "They are counted in the totals but not itemised, because a code used "
         "once or twice could be traced back to a single patient. They are "
         "almost all long-tail conditions that will end in All others as well."
         % f"{tail:,}", INK),
        ("", INK),
        ("Where the figures come from", BOLD),
        ("ClinicMaster, database ClinicMasterMOH, outpatient diagnoses recorded "
         "between 1 and 31 August 2026, read by scripts/sql/"
         "15_august_reconciliation.sql. Each ICD-11 code was put through the "
         "compiler's own mapping, so these are the figures the compiler "
         "produces, not an independent recount.", INK),
    ]
    for i, (text, font) in enumerate(lines, start=1):
        c = ws.cell(row=i, column=1, value=text)
        c.font = font
        c.alignment = WRAP
    ws.row_dimensions[1].height = 22

    # ----------------------------------------------------------- all others
    ws = wb.create_sheet("All others")
    widths(ws, {"A": 14, "B": 52, "C": 12, "D": 12, "E": 30, "F": 16, "G": 58})
    ws.cell(row=1, column=1, value="Conditions reported as 105-OP01 All others, "
                                   "August 2026").font = TITLE
    ws.cell(row=2, column=1,
            value="Column F is yours to fill in. Enter an HMIS 105 code, or "
                  "Keep if All others is correct.").font = MUTED
    head(ws, 4, ["ClinicMaster code", "Condition as ClinicMaster names it",
                 "August rows", "Share of the month", "Could be reported as",
                 "Decision", "Note"])

    first = 5
    # An example row, so the expected format is unambiguous. It is real data.
    example = ("AA03", "OTOMYCOSIS", 25, "EN17 Other ENT conditions", "EN17",
               "Example row - overwrite it. Fungal ear infection, which the "
               "ENT catch-all already covers.")
    body = [example] + [
        (code, name, n,
         "%s %s" % SUGGESTED[code] if code in SUGGESTED else "",
         "",
         NOTE_POLICY if is_policy(name) else
         ("" if code in SUGGESTED else NOTE_NO_LINE))
        for code, name, n in others if code != "AA03"
    ]

    # Rows are worked out once, here, rather than inline in the formula. The
    # first draft wrote "first + len(body) + 1" into the divisor, which landed
    # on the not-itemised line rather than the month total, and every share in
    # the column came out roughly four times too big. A share is only as good
    # as its denominator, and an arithmetic expression buried in an f-string is
    # not somewhere a wrong denominator shows itself.
    total_row = first + len(body)
    tail_row = total_row + 1
    month_row = total_row + 2

    r = first
    for code, name, n, suggest, decision, note in body:
        ws.cell(row=r, column=1, value=code).font = INK
        ws.cell(row=r, column=2, value=name).font = INK
        ws.cell(row=r, column=3, value=n).font = INK
        share = ws.cell(row=r, column=4, value=f"=C{r}/$C${month_row}")
        share.font, share.number_format = INK, "0.0%"
        ws.cell(row=r, column=5, value=suggest).font = INK
        d = ws.cell(row=r, column=6, value=decision)
        d.font, d.fill = INK, FILL_IN
        c = ws.cell(row=r, column=7, value=note)
        c.font, c.alignment = INK, WRAP
        for col in "ABCEF":
            ws[f"{col}{r}"].alignment = TOP
        r += 1

    assert r == total_row, (r, total_row)
    t = ws.cell(row=total_row, column=2, value="Total reported as All others")
    t.font = BOLD
    s = ws.cell(row=total_row, column=3, value=f"=SUM(C{first}:C{total_row - 1})")
    s.font = BOLD
    ws.cell(row=tail_row, column=2,
            value="Codes used fewer than five times, not itemised").font = INK
    ws.cell(row=tail_row, column=3, value=tail).font = INK
    ws.cell(row=month_row, column=2, value="All outpatient diagnoses in August").font = BOLD
    m = ws.cell(row=month_row, column=3, value=month)
    m.font = BOLD
    ws.cell(row=month_row + 1, column=2,
            value="Source: ClinicMaster, 1-31 August 2026. Total supplied by "
                  "15_august_reconciliation.sql section 3.").font = MUTED

    # ------------------------------------------------------- the whole form
    ws = wb.create_sheet("August 105-01")
    widths(ws, {"A": 14, "B": 70, "C": 14, "D": 14})
    ws.cell(row=1, column=1,
            value="HMIS 105:01 outpatient diagnoses, August 2026, as the "
                  "compiler maps them").font = TITLE
    ws.cell(row=2, column=1,
            value="Recomputed from ClinicMaster. Excludes %s diagnoses in codes "
                  "used fewer than five times." % f"{tail:,}").font = MUTED
    head(ws, 4, ["HMIS code", "Data element", "August rows",
                 "Share of itemised"])

    first = 5
    ordered = sorted(totals.items(), key=lambda kv: -kv[1])
    r = first
    for code, n in ordered:
        ws.cell(row=r, column=1, value=code).font = INK
        e = ws.cell(row=r, column=2,
                    value=names.get(code, "").split(". ", 1)[-1])
        e.font = INK
        ws.cell(row=r, column=3, value=n).font = INK
        share = ws.cell(row=r, column=4,
                        value=f"=C{r}/$C${first + len(ordered)}")
        share.font, share.number_format = INK, "0.0%"
        r += 1
    ws.cell(row=r, column=2, value="Total itemised").font = BOLD
    ws.cell(row=r, column=3, value=f"=SUM(C{first}:C{r - 1})").font = BOLD

    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False

    wb.save(out)
    return out, len(others), totals["OP01"], month, tail


if __name__ == "__main__":
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "JRRH_105_August2026_all_others_review.xlsx"
    path, n, op01, month, tail = build(src, out)
    print(f"wrote {path}: {n} conditions, {op01:,} rows itemised as All others, "
          f"month {month:,}, untitemised tail {tail:,}")
