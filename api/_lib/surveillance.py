"""HMIS 033B - Weekly Epidemiological Surveillance Report.

Unlike 105:01 and 108, which are line-listed registers aggregated by age band
and sex, 033B is a *tally* form. All 239 of its data elements sit on the
default category combination, and each carries a single number for the week.
There is no disaggregation to compute.

The import format is therefore a two-column tally (Code, Value) rather than a
patient-level extract. Codes ClinicMaster can supply are pre-filled by the
extraction queries under scripts/sql/; the remainder - tracer medicine and ARV
stock balances, GeneXpert cartridges remaining, modules working - are keyed in,
because no register holds them and no query can invent them.

Code suffix convention used by the national instance:
    a = Cases       b = Deaths      c = Cases Tested      d = Cases Positive
Summary-section codes (AP, MA, TB, TR, RV, GP, TP) carry no suffix.
"""
import re

from .metadata import mapping
# Period arithmetic lives in periods.py, which serves all three cadences.
# Re-exported here so existing callers and tests keep working unchanged.
from .periods import (  # noqa: F401
    WEEK_RE as WEEK_PERIOD_RE,
    describe_week,
    parse_week_period,
    week_bounds,
    week_period,
)

SURV_COLUMNS = ["Code", "Value"]

_SURV_INDEX = None


def surveillance_index() -> dict:
    """Upper-cased code -> data element id, so 'cd01a' and 'CD01a' both resolve."""
    global _SURV_INDEX
    if _SURV_INDEX is not None:
        return _SURV_INDEX
    idx = mapping().get("HMIS033B_codeIndex", {})
    if not idx:
        # The 105/108 metadata can be served from a cache written before 033B
        # existed. Failing loudly here beats accepting a tally and silently
        # compiling nothing, which looks like a data problem rather than a
        # configuration one.
        raise RuntimeError(
            "The HMIS 033B data element list is empty. The cached DHIS2 metadata "
            "predates this report. Set DHIS2_USERNAME and DHIS2_PASSWORD (or "
            "DHIS2_PAT) and run Refresh metadata in the admin page."
        )
    _SURV_INDEX = {str(k).upper(): v for k, v in idx.items()}
    return _SURV_INDEX


def reset_index():
    global _SURV_INDEX
    _SURV_INDEX = None


def _clean_value(raw):
    """Return (value, error). Blank means 'not reported' and is skipped, which is
    materially different from a reported zero - DHIS2 stores the two differently."""
    text = str(raw if raw is not None else "").strip().replace(",", "")
    if text == "":
        return None, None
    try:
        num = float(text)
    except ValueError:
        return None, f"Value '{raw}' is not a number"
    if num < 0:
        return None, f"Value '{raw}' is negative"
    if num != int(num):
        return None, f"Value '{raw}' must be a whole number"
    return int(num), None


METADATA_PREFIX = "_"

# Relationships the form itself implies. Each is (left codes, right codes,
# message): the sum of the left may not exceed the sum of the right.
#
# These exist because three weeks of this report were compiled from figures
# that were internally impossible and nobody could see it. Week 35 of 2026 was
# reported with 3,619 new attendances out of 3,619 total, 21 GeneXpert samples
# rejected out of 21 tested, and 173 rapid tests conducted with no result of
# any kind. Every one of those is arithmetic a person would catch in a moment
# and a spreadsheet never will.
SUBSET_RULES = [
    (["MA03"], ["MA02"], "RDT positives cannot exceed the RDTs tested"),
    (["MA05"], ["MA04"], "microscopy positives cannot exceed the smears tested"),
    (["MA08"], ["MA03"], "RDT positives treated cannot exceed RDT positives"),
    (["MA10"], ["MA05"], "microscopy positives treated cannot exceed microscopy positives"),
    (["MA07"], ["MA02"], "RDT negatives treated cannot exceed the RDTs tested"),
    (["MA09"], ["MA04"], "microscopy negatives treated cannot exceed the smears tested"),
    (["GP03", "GP05"], ["GP01"],
     "samples detected plus errors cannot exceed the samples tested"),
    (["GP04"], ["GP03"], "rifampicin resistance cannot exceed the MTB detections"),
    (["AP01"], ["AP02"], "new attendances cannot exceed total attendance"),
    (["AP03"], ["AP02"], "deaths cannot exceed total attendance"),
]

# Two figures being exactly equal is not impossible, but in this report it has
# so far always meant a filter that matched nothing. Warnings, not errors.
EQUALITY_WARNINGS = [
    ("AP01", "AP02", "every attendance is counted as new - check the "
                     "new-versus-repeat rule for the period"),
    ("GP02", "GP01", "every GeneXpert sample is counted as rejected - check "
                     "the rejection code"),
]


def check_consistency(clean_rows: list, context: dict = None) -> list:
    """Arithmetic the form implies but cannot enforce. Returns a list of
    {severity, message}: 'error' for a figure that cannot be true, 'warning'
    for one that is possible but has previously only ever been a bug."""
    got = {r["code"].upper(): r["value"] for r in clean_rows or []}
    out = []

    for left, right, why in SUBSET_RULES:
        if not any(c in got for c in left) or not all(c in got for c in right):
            continue
        lsum = sum(got.get(c, 0) for c in left)
        rsum = sum(got[c] for c in right)
        if lsum > rsum:
            out.append({"severity": "error",
                        "message": f"{'+'.join(left)} is {lsum} but {'+'.join(right)} "
                                   f"is {rsum}: {why}."})

    for a, b, why in EQUALITY_WARNINGS:
        if a in got and b in got and got[a] == got[b] and got[b] > 0:
            out.append({"severity": "warning",
                        "message": f"{a} equals {b} at {got[b]}: {why}."})

    # Ordered against resulted, where the extract recorded both. A test ordered
    # and never resulted was not a test, and reporting it as one overstates the
    # denominator and halves the positivity.
    for code, meta, what in (("MA02", "_req_rdt", "rapid tests"),
                             ("MA04", "_req_smear", "smears"),
                             ("GP01", "_req_xpert", "GeneXpert samples")):
        ordered = (context or {}).get(meta)
        if code not in got or not str(ordered or "").strip().isdigit():
            continue
        ordered = int(ordered)
        if ordered > got[code]:
            gap = ordered - got[code]
            sev = "warning" if got[code] else "error"
            tail = ("none was resulted, so nothing can be reported for this week"
                    if not got[code] else f"{gap} were ordered but never resulted")
            out.append({"severity": sev,
                        "message": f"{ordered} {what} ordered, {got[code]} resulted: {tail}."})
    return out


def validate_surveillance_rows(rows: list, period: str):
    """Validate a 033B tally. Returns (clean_rows, errors, context)."""
    index = surveillance_index()
    errors, clean, seen, context = [], [], {}, {}

    if not parse_week_period(period):
        return [], [{"line": 1, "patient": "", "problems": [
            f"'{period}' is not a valid weekly period. Use YYYYWnn, for example 2026W34."]}], {}

    for i, row in enumerate(rows, start=2):  # header is line 1
        row = {str(k).strip(): v for k, v in row.items() if k}
        code_raw = str(row.get("Code") or row.get("code") or "").strip()
        value_raw = row.get("Value", row.get("value", ""))
        problems = []

        if not code_raw:
            continue  # a blank code line is padding, not an error

        # Rows whose code begins with an underscore are extract metadata, not
        # tally codes: the period the extract actually covered, and how many
        # tests were ordered against how many were resulted. The extraction
        # script emits them so that a figure can be audited after the fact.
        # They must be carried, not rejected - reported as unknown codes they
        # look like a data fault, and the obvious response is to delete the
        # very rows that explain the numbers.
        if code_raw.startswith(METADATA_PREFIX):
            context[code_raw] = str(value_raw).strip()
            continue

        code_norm = re.sub(r"\s+", "", code_raw).upper()
        # Tolerate the full element name being pasted in, e.g. '033B-CD01a'
        code_norm = re.sub(r"^033B[-\s]?", "", code_norm)
        de_id = index.get(code_norm)
        if not de_id:
            problems.append(f"Code '{code_raw}' does not match any HMIS 033B data element")

        value, verr = _clean_value(value_raw)
        if verr:
            problems.append(verr)

        if de_id and value is not None and code_norm in seen:
            problems.append(f"Code '{code_raw}' appears more than once (first at line {seen[code_norm]})")

        if problems:
            errors.append({"line": i, "patient": code_raw, "problems": problems})
            continue
        if value is None:
            continue  # not reported this week

        seen[code_norm] = i
        clean.append({
            "code": code_norm,
            "data_element": de_id,
            "value": value,
            "in_period": True,
        })
    return clean, errors, context


def compile_033b(rows: list, period: str):
    """Map a validated tally onto DHIS2 data values. Every element is default-
    disaggregated, so this is a direct translation rather than an aggregation."""
    m = mapping()
    des = m["dataElements"]["HMIS033B"]
    default_coc = m["categoryCombos"]["DEFAULT"]["cocs"]["default"]
    index = surveillance_index()

    values, unmapped, seen = [], {}, set()
    for r in rows:
        code = str(r.get("code") or "").upper()
        de_id = r.get("data_element") or index.get(code)
        if not de_id:
            unmapped[code] = unmapped.get(code, 0) + 1
            continue
        if de_id in seen:
            continue
        seen.add(de_id)
        values.append({
            "dataElement": de_id,
            "dataElementName": des.get(de_id, {}).get("name", code),
            "categoryOptionCombo": default_coc,
            "categoryOptionComboName": "default",
            "value": str(r["value"]),
        })
    values.sort(key=lambda v: v["dataElementName"])
    return values, [{"code": k, "records": v} for k, v in sorted(unmapped.items())]


def template_csv() -> str:
    """Build the blank 033B tally from live metadata, so the template can never
    drift from what the national instance actually accepts."""
    m = mapping()
    des = m["dataElements"]["HMIS033B"]
    rows = []
    for de_id, info in des.items():
        code = info.get("code")
        if not code:
            continue
        label = re.sub(r"^033[Bb][-\s][A-Za-z0-9_]+[\.\s]\s*", "", info.get("name", "")).strip()
        rows.append((code, label))

    def sort_key(item):
        code = item[0]
        m2 = re.match(r"^([A-Za-z]+)(\d+)([a-z]?)(.*)$", code)
        if not m2:
            return (code, 0, "", "")
        return (m2.group(1), int(m2.group(2)), m2.group(3), m2.group(4))

    rows.sort(key=sort_key)
    out = ["Code,Label,Value"]
    for code, label in rows:
        safe = label.replace('"', "'")
        out.append(f'{code},"{safe}",')
    return "\n".join(out) + "\n"
