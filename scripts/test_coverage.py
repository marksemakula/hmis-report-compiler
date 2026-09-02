"""Offline checks for zero-fill and form coverage.

The rule these checks defend is short and easy to lose: we print a zero only
where this compiler answers for the cell, and we never send one to DHIS2.

Both halves matter and for different reasons.

  * Print a zero in a column another team fills from a paper register and the
    form asserts, in our name, that their work found nothing.
  * Send a zero to DHIS2 and it is dropped in silence — measured against the
    live instance, an import of "1" reports imported=1 and the same element
    with "0" reports imported=0, ignored=0, no conflict. An app that counted
    those as written would report six thousand values submitted where the
    server kept a hundred.

    python scripts/test_coverage.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import metadata  # noqa: E402

# A fixture shaped like the real 105:01: attendance and conditions on the OPD
# age-and-sex disaggregation, plus elements on other combinations standing for
# the nutrition, rehabilitation and GBV sections other staff fill in.
OPD_AGE_SEX = metadata.CONSTANTS["categoryCombos"]["OPD_AGE_SEX"]["id"]
DEFAULT_CC = metadata.CONSTANTS["categoryCombos"]["DEFAULT"]["id"]
GBV_CC = metadata.CONSTANTS["categoryCombos"]["WARD_TYPE"]["id"]  # stand-in: not ours

DES = {
    "sv6SeKroHPV": {"name": "105-OA01. New attendance", "code": "OA01",
                    "categoryCombo": OPD_AGE_SEX, "zeroIsSignificant": False},
    "sQ4EexvvhVe": {"name": "105-OA02. Re-attendance", "code": "OA02",
                    "categoryCombo": OPD_AGE_SEX, "zeroIsSignificant": False},
    "de_malaria":  {"name": "105-EP01c. Malaria (Confirmed)", "code": "EP01c",
                    "categoryCombo": OPD_AGE_SEX, "zeroIsSignificant": False},
    "de_epilepsy": {"name": "105-MH26. Epilepsy", "code": "MH26",
                    "categoryCombo": OPD_AGE_SEX, "zeroIsSignificant": False},
    "de_default":  {"name": "105-OP01. All others", "code": "OP01",
                    "categoryCombo": DEFAULT_CC, "zeroIsSignificant": False},
    "de_nutrition": {"name": "105-NA07. Children admitted to OTC", "code": "NA07",
                     "categoryCombo": GBV_CC, "zeroIsSignificant": False},
}
metadata._MAPPING = {
    **metadata.CONSTANTS,
    "dataElements": {"HMIS105_01": DES, "HMIS108": {}, "HMIS033B": {}},
    "HMIS105_01_codeIndex": metadata._build_code_index(DES),
    "HMIS108_codeIndex": {},
    "HMIS033B_codeIndex": {},
}

from _lib import coverage  # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


print("\nOwnership follows the disaggregation, not the name prefix")
owned = coverage.owned_elements("OPD")
check("attendance is ours", "sv6SeKroHPV" in owned and "sQ4EexvvhVe" in owned, True)
check("conditions on the OPD age/sex grid are ours",
      {"de_malaria", "de_epilepsy"} <= owned, True)
check("a section on another disaggregation is NOT ours", "de_nutrition" in owned, False)
check("the default-combo element is writable but not zero-filled",
      "de_default" in owned, False)
check("a report with no compiler owns nothing", coverage.owned_elements("MCH"), set())
check("an unknown report owns nothing", coverage.owned_elements("NOPE"), set())

print("\nThe form's true denominator")
cells = coverage.dataset_cells("OPD")
# 4 elements x 10 OPD age/sex cells, 1 x 1 default, 1 x 20 ward-type stand-in.
check("every element contributes its own combination's cells", len(cells), 4 * 10 + 1 + 20)
check("no duplicate cells", len(set(cells)), len(cells))

print("\nZero-fill")
compiled = [
    {"dataElement": "sv6SeKroHPV", "categoryOptionCombo":
     metadata.CONSTANTS["categoryCombos"]["OPD_AGE_SEX"]["cocs"]["20+Yrs, Female"],
     "value": "412"},
    {"dataElement": "de_malaria", "categoryOptionCombo":
     metadata.CONSTANTS["categoryCombos"]["OPD_AGE_SEX"]["cocs"]["5-9Yrs, Male"],
     "value": "37"},
]
shown, cov = coverage.zero_fill(compiled, "OPD")
zeros = [v for v in shown if v.get("imputed")]
check("compiled values are preserved untouched",
      [v for v in shown if not v.get("imputed")], compiled)
check("every owned cell is now present",
      len([v for v in shown
           if v["dataElement"] in coverage.owned_elements("OPD")]), 4 * 10)
check("zeros fill exactly the owned cells we did not compile", len(zeros), 4 * 10 - 2)
check("every zero is the string '0'", {v["value"] for v in zeros}, {"0"})
check("no zero lands on a section that is not ours",
      [v for v in zeros if v["dataElement"] == "de_nutrition"], [])
check("no zero lands on the default-combo element",
      [v for v in zeros if v["dataElement"] == "de_default"], [])
check("a cell already compiled is never also zeroed",
      len({(v["dataElement"], v["categoryOptionCombo"]) for v in shown}), len(shown))

print("\nThe summary a reader is shown")
check("cells", cov["cells"], 61)
check("owned", cov["owned"], 40)
check("compiled", cov["compiled"], 2)
check("zeroFilled", cov["zeroFilled"], 38)
check("notOurs", cov["notOurs"], 21)
check("owned plus not-ours accounts for the whole form",
      cov["owned"] + cov["notOurs"], cov["cells"])

print("\nZeros must never reach DHIS2")
# The push payload is built from a report's stored compiled_data, which is what
# the compiler returned. zero_fill is a rendering step and its output must be
# distinguishable, so that no future caller can hand it to the push by accident.
check("every imputed value is flagged",
      all(v.get("imputed") for v in shown if v["value"] == "0" and v not in compiled), True)
check("nothing the compiler produced is flagged",
      any(v.get("imputed") for v in compiled), False)
real = [v for v in shown if not v.get("imputed")]
check("stripping imputed values returns exactly the compiled set", real, compiled)

# The payload builder is the last gate. Hand it the *displayed* values — the
# mistake a future caller is most likely to make — and it must still send only
# what was measured.
from _lib import dhis2  # noqa: E402
# The attribute option combo is resolved from the live instance. Stubbed here
# so the filter can be checked on a machine with no credentials and no network,
# which is the point of this suite.
dhis2.resolve_attribute_option_combo = lambda *a, **k: None
payload = dhis2.build_payload("OPD", "202606", shown)
check("build_payload drops every imputed zero", len(payload["dataValues"]), len(compiled))
check("build_payload keeps the measured figures",
      sorted(v["value"] for v in payload["dataValues"]), ["37", "412"])
check("no zero survives into the payload",
      [v for v in payload["dataValues"] if v["value"] == "0"], [])

print("\nA measured zero and an imputed zero must be distinguishable")
from _lib import forms  # noqa: E402
measured_zero = {"dataElement": "de_epilepsy", "categoryOptionCombo":
                 metadata.CONSTANTS["categoryCombos"]["OPD_AGE_SEX"]["cocs"]["20+Yrs, Male"],
                 "value": "0"}
shown2, _ = coverage.zero_fill(compiled + [measured_zero], "OPD")
keys = forms.imputed_keys(shown2)
mkey = f'{measured_zero["dataElement"]}-{measured_zero["categoryOptionCombo"]}'
check("a compiled zero is not marked imputed", mkey in keys, False)
check("imputed keys cover the rest", len(keys), 4 * 10 - 3)

print("\nEmpty and degenerate inputs")
check("no compiled values still zero-fills the owned grid",
      coverage.zero_fill([], "OPD")[1]["zeroFilled"], 40)
check("None is treated as empty", coverage.zero_fill(None, "OPD")[1]["compiled"], 0)
check("a report with no compiler zero-fills nothing",
      coverage.zero_fill([], "MCH")[1]["zeroFilled"], 0)

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
