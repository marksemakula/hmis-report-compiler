"""Checks for the 105:01 consistency rules.

Every figure below is real: JRRH's own EP01 series read from the national
instance for 2020 to 2024.

    year   a susp   b test   c conf   d ctrt    e trt   b_2019     c/a
    2020     3965        -     2905        -     2976     3110   73.3%
    2021     3076        -     2515        -     2524     2577   81.8%
    2022     2955        -     2339        -     2357     2425   79.2%
    2023     5912        -     1977        -     1977     1977   33.4%
    2024     6219        -     1689        -     1689     1695   27.2%

Four faults are visible in it and each has a check below: two links of the
five-element chain never reported at all, confirmed and treated becoming
identical in 2023, a positivity of 73 to 82 per cent that cannot be true, and a
retired element still receiving data every year.

    python scripts/test_consistency.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import consistency as cy  # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


def vals(**codes):
    """Compiled data values, split across two disaggregations to prove the
    rules compare TOTALS rather than matching cells."""
    out = []
    for code, n in codes.items():
        name = f"105-{code}. x"
        out.append({"dataElementName": name, "value": str(n // 2)})
        out.append({"dataElementName": name, "value": str(n - n // 2)})
    return out


def msgs(findings, severity=None):
    return [f["message"] for f in findings
            if severity is None or f["severity"] == severity]


def has(findings, fragment, severity=None):
    return any(fragment in m for m in msgs(findings, severity))


print("\nTotals are summed across every age band and sex")
t = cy.totals_by_code(vals(EP01a=3965, EP01c=2905))
check("split cells are summed", (t["EP01a"], t["EP01c"]), (3965, 2905))
check("an imputed zero is not a measurement",
      cy.totals_by_code([{"dataElementName": "105-EP01a. x", "value": "0", "imputed": True}]), {})
check("a non-numeric value is ignored, not crashed on",
      cy.totals_by_code([{"dataElementName": "105-EP01a. x", "value": ""}]), {})
check("an unparseable element name is skipped",
      cy.totals_by_code([{"dataElementName": "no code here", "value": "5"}]), {})

print("\nThe chain: each element is a subset of the one before it")
check("tested above suspected is impossible",
      has(cy.check_opd(vals(EP01a=100, EP01b=120)), "cannot exceed suspected", "error"), True)
check("confirmed above tested is impossible",
      has(cy.check_opd(vals(EP01b=100, EP01c=120)), "cannot exceed malaria tested", "error"), True)
check("confirmed above suspected is impossible",
      has(cy.check_opd(vals(EP01a=100, EP01c=120)), "cannot exceed suspected", "error"), True)
check("confirmed treated above confirmed is impossible",
      has(cy.check_opd(vals(EP01c=100, EP01d=120)), "cannot exceed confirmed cases", "error"), True)
check("confirmed treated above total treated is impossible",
      has(cy.check_opd(vals(EP01d=120, EP01e=100)), "cannot exceed total treated", "error"), True)
check("a properly ordered chain raises no error",
      msgs(cy.check_opd(vals(EP01a=1000, EP01b=800, EP01c=300, EP01d=290, EP01e=310)),
           "error"), [])

print("\nThe two links Jinja has never reported")
f = cy.check_opd(vals(EP01c=1689, EP01e=1689))
check("a confirmed count with no tested count is flagged",
      has(f, "EP01b (Malaria Tested) is blank", "warning"), True)
check("...and says how long it has been so", has(f, "since 2020"), True)
check("a treated count with no confirmed-treated count is flagged",
      has(f, "EP01d", "warning"), True)
check("supplying EP01b clears the first warning",
      has(cy.check_opd(vals(EP01a=5000, EP01b=2000, EP01c=600)),
          "EP01b (Malaria Tested) is blank"), False)

print("\nConfirmed and treated being identical, as they were in 2023 and 2024")
check("identical figures are flagged",
      has(cy.check_opd(vals(EP01c=1977, EP01e=1977)), "copied into the other", "warning"), True)
check("2022's small difference is not flagged",
      has(cy.check_opd(vals(EP01c=2339, EP01e=2357)), "copied into the other"), False)
check("identical is a warning, never an error",
      msgs(cy.check_opd(vals(EP01c=1977, EP01e=1977)), "error"), [])

print("\nTest positivity, against whichever denominator exists")
# Match the RATE message specifically. The "EP01b is blank" warning also
# contains the word positivity, and a looser match passed against the wrong one.
check("2021's 81.8% is flagged as implausible",
      has(cy.check_opd(vals(EP01a=3076, EP01c=2515)), "denominator is too small", "warning"), True)
check("2024's 27.2% is not flagged",
      has(cy.check_opd(vals(EP01a=6219, EP01c=1689)), "denominator is too small"), False)
check("an implausibly low rate is flagged the other way",
      has(cy.check_opd(vals(EP01a=10000, EP01c=50)), "under-counted", "warning"), True)
check("EP01b is preferred as the denominator when present",
      has(cy.check_opd(vals(EP01a=10000, EP01b=200, EP01c=180)), "of 200 tested"), True)

print("\nThe retired element that still receives data")
check("reporting into EP01b_2019 is an error",
      has(cy.check_opd(vals(EP01b_2019=1695)), "retired", "error"), True)
check("...and names the years it happened", has(cy.check_opd(vals(EP01b_2019=1695)), "2020 to 2024"), True)
check("not reporting into it raises nothing",
      has(cy.check_opd(vals(EP01c=100)), "retired"), False)

print("\nAttendance")
check("new attendance above the total is impossible",
      has(cy.check_opd(vals(OA01=100, OA02=0)), "cannot exceed total attendance"), False)
check("...but genuinely exceeding it is caught",
      has(cy.check_opd([{"dataElementName": "105-OA01. x", "value": "150"},
                        {"dataElementName": "105-OA02. x", "value": "-100"}]),
          "cannot exceed total attendance", "error"), True)

print("\nDegenerate input")
check("no values", cy.check_opd([]), [])
check("None", cy.check_opd(None), [])
check("a rule with only one side present is not applied",
      msgs(cy.check_opd(vals(EP01d=50)), "error"), [])

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
