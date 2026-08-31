"""Offline checks for period handling and the read-only form renderer.

Runs without a database, DHIS2 credentials or network access.

    python scripts/test_forms.py
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))

from _lib import metadata, periods  # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


print("\nAll eight reports are registered with the official naming")
rts = metadata.CONSTANTS["reportTypes"]
check("eight report types", len(rts), 8)
check("eight data sets", len(metadata.CONSTANTS["dataSets"]), 8)
for rt, e in rts.items():
    check(f"{rt} points at a registered data set",
          e["dataSet"] in metadata.CONSTANTS["dataSets"], True)
check("cadences", sorted({e["periodType"] for e in rts.values()}),
      ["Monthly", "Quarterly", "Weekly"])
check("compilers written so far",
      sorted(k for k, v in rts.items() if v["compiler"]), ["IPD", "OPD", "SURV"])
check("106a:01-02 is quarterly", rts["HIV"]["periodType"], "Quarterly")
check("105C name matches the instance",
      metadata.CONSTANTS["dataSets"]["HMIS105C"]["name"],
      "HMIS 105C- Palliative Care Monthly Report")

print("\nElement-name prefixes across the eight data sets")
import re  # noqa: E402
RX = re.compile(r"^(105[A-Ca-c]?|106[Aa]|108|033[Bb])-([A-Za-z0-9_]+)[\.\s]\s*(.*)$")
for name, code in [
    ("105-OA01. New attendance", "OA01"),
    ("105C-PC03. Patients on morphine", "PC03"),
    ("106a-HC01. New clients enrolled in HIV care", "HC01"),
    ("106a-HC45a_2019. Clients failing first line", "HC45a_2019"),
    ("108-CD01a. Cholera - Cases", "CD01a"),
    ("033B-CD01a. Malaria (Confirmed) - Cases", "CD01a"),
    ("033b-AP03. Total Deaths", "AP03"),
    ("033B-CD23e_2019 Other Cases 2 (Positive)", "CD23e_2019"),
]:
    m = RX.match(name)
    check(f"parses: {name[:38]}", m.group(2) if m else None, code)

print("\nPeriod identifiers")
check("monthly parse", periods.parse("Monthly", "202606"), (2026, 6))
check("monthly month 13 rejected", periods.parse("Monthly", "202613"), None)
check("monthly describe", periods.describe("Monthly", "202606"), "June 2026")
check("monthly bounds", periods.month_bounds("202602"), (date(2026, 2, 1), date(2026, 2, 28)))
check("december bounds roll the year", periods.month_bounds("202612"), (date(2026, 12, 1), date(2026, 12, 31)))

check("quarterly parse", periods.parse("Quarterly", "2026Q3"), (2026, 3))
check("quarterly Q5 rejected", periods.parse("Quarterly", "2026Q5"), None)
check("quarterly describe", periods.describe("Quarterly", "2026Q3"), "Q3 2026 (July–September)")
check("quarterly bounds", periods.quarter_bounds("2026Q1"), (date(2026, 1, 1), date(2026, 3, 31)))
check("Q4 bounds roll the year", periods.quarter_bounds("2026Q4"), (date(2026, 10, 1), date(2026, 12, 31)))

check("weekly parse", periods.parse("Weekly", "2026W35"), (2026, 35))
check("weekly bounds Mon-Sun", periods.week_bounds("2026W35"), (date(2026, 8, 24), date(2026, 8, 30)))
check("cadence mismatch rejected", periods.parse("Monthly", "2026W35"), None)
check("cadence mismatch rejected, other way", periods.parse("Weekly", "202606"), None)

check("default monthly is last closed month",
      periods.default_period("Monthly", date(2026, 8, 25)), "202607")
check("default monthly across new year",
      periods.default_period("Monthly", date(2026, 1, 9)), "202512")
check("default quarterly is last closed quarter",
      periods.default_period("Quarterly", date(2026, 8, 25)), "2026Q2")
check("default quarterly across new year",
      periods.default_period("Quarterly", date(2026, 2, 3)), "2025Q4")
check("default weekly is last week",
      periods.default_period("Weekly", date(2026, 8, 25)), "2026W34")

# --------------------------------------------------------------- forms
metadata._MAPPING = {
    **metadata.CONSTANTS,
    "dataElements": {k: {} for k in metadata.CONSTANTS["dataSets"]},
    **{f"{k}_codeIndex": {} for k in metadata.CONSTANTS["dataSets"]},
}
from _lib import forms  # noqa: E402

DIRTY = (
    "<style>td{border:1px solid #999}</style>"
    "<table><tr><td>OPD New attendance</td>"
    '<td><input id="sv6SeKroHPV-zh2zAaHyYQx-val" name="entryfield" '
    'onchange="saveVal(this)" title="OA01"></td>'
    '<td><input id="sQ4EexvvhVe-wDiX34aiw6i-val" onblur="x()"></td>'
    '<td><input id="total_ABC" readonly></td>'
    '<td><select id="pick"><option>a</option></select></td>'
    '<td><textarea id="cmt">note</textarea></td></tr></table>'
    '<a href="javascript:alert(1)">x</a>'
    "<script>alert('boom')</script>"
    '<script src="https://evil.example/x.js"></script>'
)

skel = forms.sanitise(DIRTY)
print("\nSanitising a DHIS2 custom form")
check("no script tags survive", "<script" in skel.lower(), False)
check("no inline handlers survive", "onchange" in skel.lower() or "onblur" in skel.lower(), False)
check("no javascript: URLs survive", "javascript:" in skel.lower(), False)
check("no inputs survive", "<input" in skel.lower(), False)
check("no selects survive", "<select" in skel.lower(), False)
check("no textareas survive", "<textarea" in skel.lower(), False)
check("styles are kept for layout", "<style>" in skel, True)
check("table structure is kept", skel.count("<td>"), 6)
check("labels are kept", "OPD New attendance" in skel, True)
check("keyed slots", skel.count('data-k="sv6SeKroHPV-zh2zAaHyYQx"'), 1)
check("non-DHIS2 field becomes an unkeyed slot", skel.count('data-k=""'), 3)

forms._SKELETONS["HMIS105_01"] = skel

print("\nRendering with values")
VALUES = forms.values_map([
    {"dataElement": "sv6SeKroHPV", "categoryOptionCombo": "zh2zAaHyYQx", "value": "76348"},
    {"dataElement": "sQ4EexvvhVe", "categoryOptionCombo": "wDiX34aiw6i", "value": "<b>34432</b>"},
])
check("values_map keys", sorted(VALUES), ["sQ4EexvvhVe-wDiX34aiw6i", "sv6SeKroHPV-zh2zAaHyYQx"])

doc = forms.render_document("OPD", "202606", "June 2026", VALUES,
                            {"report_id": 12, "push_status": "PENDING"})
check("is a complete document", doc.startswith("<!doctype html>"), True)
check("official data set name in the header",
      "HMIS 105:01 - OPD Monthly Report" in doc, True)
check("period shown", "202606" in doc and "June 2026" in doc, True)
check("filled value rendered", '<span class="hv filled">76348</span>' in doc, True)
check("value HTML is escaped, not injected", "&lt;b&gt;34432&lt;/b&gt;" in doc, True)
check("no raw bold tag from the value", "<b>34432</b>" in doc, False)
check("unmatched fields render empty", doc.count('<span class="hv empty">'), 3)
check("pending submission is flagged", "not yet submitted" in doc, True)
check("no script in the rendered document", "<script" in doc.lower(), False)

blank = forms.render_document("OPD", "202606", "June 2026", {}, {})
check("blank form says so", "no report compiled" in blank.lower(), True)
check("blank form has no filled cells", "hv filled" in blank, False)
check("blank form still renders the layout", "OPD New attendance" in blank, True)

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
