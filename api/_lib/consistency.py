"""Arithmetic the HMIS forms imply but cannot enforce.

033B's checks live in surveillance.py because they operate on a flat tally.
105:01 needs its own, because its values are disaggregated by age band and sex
and the relationships hold between the TOTALS, not cell by cell: a fever in a
five-year-old boy may be confirmed as malaria in that same cell, but the chain
as a whole is what the Ministry reads.

THE MALARIA CHAIN, AND WHY IT NEEDED LOOKING AT

Five elements describe one clinical pathway and each is a subset of the one
before it:

    EP01a  Suspected Malaria (fever)          everyone with a fever
    EP01b  Malaria Tested (B/s and RDT)       of those, the ones tested
    EP01c  Malaria confirmed (B/s and RDT)    of those, the ones positive
    EP01d  Confirmed Malaria cases treated    of those, the ones treated
    EP01e  Total malaria cases treated        d, plus presumptive treatment

So EP01a >= EP01b >= EP01c >= EP01d, and EP01e >= EP01d. EP01e may exceed
EP01c, because a clinician may treat a case that was never confirmed; it should
not fall below it.

Read from the national instance for Jinja RRH, 2020 to 2024:

    year   a susp   b test   c conf   d ctrt    e trt   b_2019     c/a
    2020     3965        -     2905        -     2976     3110   73.3%
    2021     3076        -     2515        -     2524     2577   81.8%
    2022     2955        -     2339        -     2357     2425   79.2%
    2023     5912        -     1977        -     1977     1977   33.4%
    2024     6219        -     1689        -     1689     1695   27.2%

Four things in that table are worth encoding as checks.

  * EP01b and EP01d have NEVER been reported. Not once in five years. Two of
    the five links in the chain are permanently absent, so nobody can see how
    many fevers were tested or how many confirmed cases were treated.

  * EP01c and EP01e are identical in 2023 and 2024, having differed by 9 to 71
    in the years before. Identical is not impossible, but it is what happens
    when one figure is copied into the other rather than counted.

  * Test positivity was 73 to 82 per cent to 2022, then 33 and 27 per cent.
    Positivity above 70 is not credible for a referral hospital; it means the
    denominator was wrong, and the 2023 jump in EP01a from 2,955 to 5,912 looks
    like a correction to how fevers were counted rather than an outbreak. Both
    shapes are worth flagging, in opposite directions.

  * EP01b_2019 "Malaria Total" is a RETIRED element and has received data every
    year including 2024. Reporting into a retired element is invisible in the
    current form and easy to continue for years.
"""
import re

# Each rule: (left codes, right codes, message). The left may not exceed the
# right once summed across every age band and sex.
OPD_SUBSET_RULES = [
    (["EP01b"], ["EP01a"], "malaria tested cannot exceed suspected malaria"),
    (["EP01c"], ["EP01b"], "malaria confirmed cannot exceed malaria tested"),
    (["EP01c"], ["EP01a"], "malaria confirmed cannot exceed suspected malaria"),
    (["EP01d"], ["EP01c"], "confirmed cases treated cannot exceed confirmed cases"),
    (["EP01d"], ["EP01e"], "confirmed cases treated cannot exceed total treated"),
    (["OA01"], ["OA01", "OA02"], "new attendance cannot exceed total attendance"),
]

# Codes that must never receive data: retired elements the form no longer shows.
RETIRED_CODES = {
    "EP01b_2019": "EP01b_2019 'Malaria Total' is retired and superseded by "
                  "EP01a to EP01e, but Jinja reported into it every year from "
                  "2020 to 2024. Anything written here is invisible on the "
                  "current form.",
}

# Positivity outside this band is worth a second look. Below, the denominator is
# probably too large; above, it is probably too small - Jinja reported 73 to 82
# per cent until 2022, which is not a credible test positivity for a referral
# hospital and reflected EP01a counting only the fevers that were tested.
POSITIVITY_LOW, POSITIVITY_HIGH = 0.02, 0.60

CODE_RE = re.compile(r"^105-([A-Za-z0-9_]+)[\.\s]")


def totals_by_code(values: list) -> dict:
    """Sum compiled data values across every disaggregation, keyed by HMIS code.

    The relationships hold between totals. Comparing cell by cell would raise
    false alarms: a fever recorded for a child may be confirmed in a different
    age band if the birth date was corrected between the two entries."""
    out = {}
    for v in values or []:
        if v.get("imputed"):
            continue                      # a rendering zero is not a measurement
        m = CODE_RE.match(str(v.get("dataElementName") or ""))
        if not m:
            continue
        try:
            n = int(str(v.get("value", "")).strip())
        except (TypeError, ValueError):
            continue
        out[m.group(1)] = out.get(m.group(1), 0) + n
    return out


def check_opd(values: list) -> list:
    """Findings for a compiled 105:01 report. Same shape as the 033B checker:
    {severity, message}, 'error' for a figure that cannot be true."""
    got = totals_by_code(values)
    out = []

    for left, right, why in OPD_SUBSET_RULES:
        if not any(c in got for c in left) or not all(c in got for c in right):
            continue
        lsum = sum(got.get(c, 0) for c in left)
        rsum = sum(got[c] for c in right)
        if lsum > rsum:
            out.append({"severity": "error",
                        "message": f"{'+'.join(left)} is {lsum} but {'+'.join(right)} "
                                   f"is {rsum}: {why}."})

    for code, why in RETIRED_CODES.items():
        if got.get(code):
            out.append({"severity": "error",
                        "message": f"{got[code]} reported against {code}. {why}"})

    # The chain's missing links. Reporting a confirmed count with no tested
    # count is the pattern this facility has followed since at least 2020.
    if got.get("EP01c") and "EP01b" not in got:
        out.append({"severity": "warning",
                    "message": f"EP01c reports {got['EP01c']} confirmed malaria cases "
                               "but EP01b (Malaria Tested) is blank, so the test "
                               "positivity cannot be computed. This has been blank "
                               "every year since 2020."})
    if got.get("EP01e") and "EP01d" not in got:
        out.append({"severity": "warning",
                    "message": f"EP01e reports {got['EP01e']} treated but EP01d "
                               "(Confirmed cases treated) is blank, so presumptive "
                               "treatment cannot be separated from confirmed."})

    # Identical is possible, but at Jinja it began in 2023 and coincided with
    # the two figures being entered as one.
    if got.get("EP01c") and got.get("EP01e") and got["EP01c"] == got["EP01e"]:
        out.append({"severity": "warning",
                    "message": f"EP01c and EP01e are both {got['EP01c']}. Total treated "
                               "usually exceeds confirmed, because presumptive cases "
                               "are treated too; identical figures usually mean one "
                               "was copied into the other."})

    # Positivity, against whichever denominator is present.
    denom_code = "EP01b" if got.get("EP01b") else ("EP01a" if got.get("EP01a") else None)
    if denom_code and got.get("EP01c"):
        rate = got["EP01c"] / got[denom_code]
        label = "tested" if denom_code == "EP01b" else "suspected"
        if rate > POSITIVITY_HIGH:
            out.append({"severity": "warning",
                        "message": f"{got['EP01c']} confirmed of {got[denom_code]} "
                                   f"{label} is {rate:.0%} positivity. Above "
                                   f"{POSITIVITY_HIGH:.0%} usually means the denominator "
                                   "is too small - Jinja reported 73 to 82 per cent "
                                   "until 2022, when EP01a counted only the fevers "
                                   "that were tested."})
        elif rate < POSITIVITY_LOW:
            out.append({"severity": "warning",
                        "message": f"{got['EP01c']} confirmed of {got[denom_code]} "
                                   f"{label} is {rate:.1%} positivity, which is low "
                                   "enough to suggest confirmed cases are being "
                                   "under-counted rather than that malaria is rare."})
    return out
