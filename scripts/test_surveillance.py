"""Offline checks for the HMIS 033B surveillance module.

Runs without a database, DHIS2 credentials or network access: the DHIS2
metadata call is replaced with a small fixture that mirrors the real naming
conventions found on the national instance, including the lowercase '033b-'
prefix and the element whose code is not followed by a full stop.

    python scripts/test_surveillance.py
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))

from _lib import metadata  # noqa: E402

FIXTURE = {
    "de_cd01a": {"name": "033B-CD01a. Malaria (Confirmed) - Cases", "code": "CD01a", "categoryCombo": "bjDvmb4bfuf"},
    "de_cd01b": {"name": "033B-CD01b. Malaria (Confirmed) - Deaths", "code": "CD01b", "categoryCombo": "bjDvmb4bfuf"},
    "de_ap03": {"name": "033b-AP03. Total Deaths", "code": "AP03", "categoryCombo": "bjDvmb4bfuf"},
    "de_cd23e": {"name": "033B-CD23e_2019 Other Cases 2 (Positive)", "code": "CD23e_2019", "categoryCombo": "bjDvmb4bfuf"},
    "de_gp07": {"name": "033B-GP07. No. of catridges remaining", "code": "GP07", "categoryCombo": "bjDvmb4bfuf"},
    "de_tr01": {"name": "033B-TR01. Artemether/Lumefantrine 20/120 mg tablet", "code": "TR01", "categoryCombo": "bjDvmb4bfuf"},
}

metadata._MAPPING = {
    **metadata.CONSTANTS,
    "dataElements": {"HMIS105_01": {}, "HMIS108": {}, "HMIS033B": FIXTURE},
    "HMIS105_01_codeIndex": {},
    "HMIS108_codeIndex": {},
    "HMIS033B_codeIndex": metadata._build_code_index(FIXTURE),
}

from _lib import surveillance as s  # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


print("\nName parsing (the regex must survive both prefix casings and the missing stop)")
check("033B- uppercase prefix", metadata._build_code_index(FIXTURE).get("CD01a"), "de_cd01a")
check("033b- lowercase prefix", metadata._build_code_index(FIXTURE).get("AP03"), "de_ap03")
check("code without a full stop", metadata._build_code_index(FIXTURE).get("CD23e_2019"), "de_cd23e")

print("\nISO weekly periods")
check("mid-year week", s.week_period(date(2026, 8, 25)), "2026W35")
check("period parses", s.parse_week_period("2026W35"), (2026, 35))
check("lowercase w accepted", s.parse_week_period("2026w7"), (2026, 7))
check("week 0 rejected", s.parse_week_period("2026W0"), None)
check("week 54 rejected", s.parse_week_period("2026W54"), None)
check("YYYYMM rejected", s.parse_week_period("202608"), None)
check("week bounds are Mon-Sun", s.week_bounds("2026W35"), (date(2026, 8, 24), date(2026, 8, 30)))
# 2026 has 53 ISO weeks; 2025 has 52. The guard must know the difference.
check("W53 valid in a 53-week year", bool(s.parse_week_period("2026W53")), date(2026, 12, 28).isocalendar()[1] == 53)
check("W53 invalid in a 52-week year", s.parse_week_period("2025W53"), None)

print("\nTally validation")
rows = [
    {"Code": "CD01a", "Value": "295"},
    {"Code": "cd01b", "Value": "1"},          # lowercase must resolve
    {"Code": "033B-AP03", "Value": "4"},      # full element prefix pasted in
    {"Code": "TR01", "Value": "1,250"},       # thousands separator
    {"Code": "GP07", "Value": ""},            # blank = not reported, skipped
    {"Code": "", "Value": "9"},               # padding line, ignored
    {"Code": "ZZ99", "Value": "3"},           # unknown code
    {"Code": "CD01a", "Value": "12"},         # duplicate
    {"Code": "CD23e_2019", "Value": "-2"},    # negative
    {"Code": "CD01b", "Value": "3.5"},        # not a whole number
]
clean, errors = s.validate_surveillance_rows(rows, "2026W35")
check("clean rows", len(clean), 4)
check("error rows", len(errors), 4)
check("value normalised", [c["value"] for c in clean if c["code"] == "TR01"], [1250])
check("blank skipped, not zeroed", [c for c in clean if c["code"] == "GP07"], [])
check("unknown code reported",
      any("does not match" in p for e in errors for p in e["problems"]), True)
check("duplicate reported",
      any("more than once" in p for e in errors for p in e["problems"]), True)
check("negative reported",
      any("negative" in p for e in errors for p in e["problems"]), True)
check("fractional reported",
      any("whole number" in p for e in errors for p in e["problems"]), True)

bad_clean, bad_errors = s.validate_surveillance_rows(rows, "202608")
check("monthly period refused outright", (len(bad_clean), len(bad_errors)), (0, 1))

print("\nCompilation")
values, unmapped = s.compile_033b(clean, "2026W35")
check("one value per reported code", len(values), 4)
check("all on the default combo",
      {v["categoryOptionCombo"] for v in values}, {"HllvX50cXC0"})
check("values are strings for DHIS2", all(isinstance(v["value"], str) for v in values), True)
check("nothing unmapped", unmapped, [])
check("malaria cases carried through",
      next(v["value"] for v in values if v["dataElement"] == "de_cd01a"), "295")

print("\nTemplate generation")
csv_text = s.template_csv()
lines = csv_text.strip().split("\n")
check("header", lines[0], "Code,Label,Value")
check("one line per element", len(lines) - 1, len(FIXTURE))
check("labels stripped of the code prefix", 'CD01a,"Malaria (Confirmed) - Cases",' in csv_text, True)
check("value column left blank", lines[1].endswith(","), True)

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
