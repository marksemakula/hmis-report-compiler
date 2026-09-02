"""Laboratory results - from ClinicMaster's vocabulary to a reportable answer.

WHERE THE VALUE LIVES

Not where you would expect. `LabResults` is a container: 2,337 of its 28,252
rows carry a non-blank `Result`. The answer is one level down in
`LabResultsEXT`, where 243,270 of 250,936 rows do - one row per analyte, keyed
by `SubTestCode`. `LabResultsEXT` has no name for that code; the names are in
`LabTestsEXT`, and the mapping below carries the ones that matter so no join is
needed at compile time.

A test can have several analytes and only one of them answers the question.
HIV serology has four - Determine, STATPAK, SD BIOLINE and FINAL RESULTS - and
malaria microscopy has Detection, Species, Stage and Parasite Density. Reading
the wrong one silently reports the wrong thing, so each test names its own.

THE VOCABULARY IS NOT CLEAN, AND CANNOT BE MADE SO

Observed at Jinja on 2 September 2026, for the same clinical concept:

    NEGATIVE · NON REACTIVE · NON-REACTIVE · Non Reactive · NOT DETECTED
    MTB NOT DETECTED · NO MPS SEEN · No Plasmodium Parasites

    POSITIVE · POSTIVE · REACTIVE · MPS + SEEN · MPS ++ SEEN · MPS +++ SEEN
    MTB DETECTED LOW,RIF resistance NOT DETECTED

`POSTIVE` is not a typing slip in the data. It is the spelling stored in
`LabPossibleResults`, the controlled list the laboratory picks from, for HIV
serology, HBsAg, TPHA, HCG-BETA and malaria RDT - so every result recorded
through the dropdown carries it. Blood grouping is worse: `Negaitve` and
`Positve`. Both spellings must therefore be accepted, and the reference table
should be corrected in ClinicMaster rather than worked around forever.

TWO ORDERING TRAPS, BOTH LIVE IN THIS DATA

  * `NON REACTIVE` contains `REACTIVE`. Test negatives before positives or
    every syphilis screen reports positive.
  * `MTB DETECTED MEDIUM,RIF resistance NOT DETECTED` contains `NOT DETECTED`.
    Test the leading clause only, or every Xpert-positive reports negative.

The two traps pull in opposite directions, which is why the order below is
fixed by tests rather than by reading.
"""
import re

# Each test names the analyte that carries its reportable answer. Codes are
# ClinicMaster's: SNOMED CT where a concept exists, local otherwise.
LAB_TESTS = {
    "372071003": {"name": "Malaria microscopy", "subtest": "01",
                  "subtest_name": "Detection", "concept": "MALARIA_MICROSCOPY"},
    "407727009": {"name": "Malaria RDT", "subtest": "407727009",
                  "subtest_name": "MRDT", "concept": "MALARIA_RDT"},
    # Determine is the screening assay and carries 212 of the 222 results.
    # FINAL RESULTS - the testing algorithm's conclusion - is filled 8 times.
    # Screening is therefore what can actually be reported, and the gap is a
    # data-quality finding rather than something to paper over.
    "165813002": {"name": "HIV serology", "subtest": "kizxvo8k",
                  "subtest_name": "Determine", "concept": "HIV_SCREEN",
                  "final_subtest": "bbniqxik"},
    "9000001":   {"name": "Xpert MTB/Rif", "subtest": "ma7dy01a",
                  "subtest_name": "MTB", "concept": "TB_XPERT",
                  "rif_subtest": "tj6l4jhh"},
    "951277":    {"name": "Urine TB LAM", "subtest": "bc126a12",
                  "subtest_name": "TB-LAM", "concept": "TB_LAM"},
    "47758006":  {"name": "HBsAg", "subtest": "47758006",
                  "subtest_name": "HBSAg", "concept": "HEPB_SURFACE_ANTIGEN"},
    "269829001": {"name": "TPHA", "subtest": "269829001",
                  "subtest_name": "TPHA", "concept": "SYPHILIS_TPHA"},
    "19869000":  {"name": "RPR", "subtest": "19869000",
                  "subtest_name": "RPR", "concept": "SYPHILIS_RPR"},
    "121980003": {"name": "CrAg", "subtest": "121980003",
                  "subtest_name": "CrAg", "concept": "CRYPTOCOCCAL_ANTIGEN"},
    "313660005": {"name": "CD4 count", "subtest": "yb11by42",
                  "subtest_name": "CD4 count", "concept": "CD4", "numeric": True},
    "315124004": {"name": "HIV viral load", "subtest": "3151240041",
                  "subtest_name": "HIV VIRAL LOAD", "concept": "HIV_VIRAL_LOAD",
                  "numeric": True},
    "399256002": {"name": "HIV-1 DNA PCR", "subtest": "399256002",
                  "subtest_name": "HIV-1 DNA PCR", "concept": "HIV_EID"},
    "28804003":  {"name": "HIV drug resistance", "subtest": "28804003",
                  "subtest_name": "HIV-DR", "concept": "HIV_DRUG_RESISTANCE"},
}

POSITIVE, NEGATIVE, INVALID, INDETERMINATE = "Positive", "Negative", "Invalid", "Indeterminate"


def _normalise(raw: str) -> str:
    """Upper-case, strip punctuation that varies, collapse whitespace.

    Hyphens go because NON-REACTIVE and NON REACTIVE are the same answer, but
    plus signs stay, because MPS + SEEN and NO MPS SEEN are not."""
    s = (raw or "").upper().replace("-", " ")
    s = re.sub(r"[^\w\s+]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Order matters and is fixed by tests. Negatives are tested first because
# NON REACTIVE contains REACTIVE and NOT DETECTED contains DETECTED.
_NEGATIVE = (
    "NO MPS SEEN", "NO PLASMODIUM PARASITES", "NO PARASITES SEEN",
    "NON REACTIVE", "NONREACTIVE", "NOT DETECTED", "NOT SEEN",
    "NEGATIVE", "NEGAITVE", "NEG", "ABSENT",
)
_POSITIVE = (
    "MPS + SEEN", "MPS ++ SEEN", "MPS +++ SEEN", "MPS SEEN", "PARASITES SEEN",
    "DETECTED", "REACTIVE", "POSITIVE", "POSTIVE", "POSITVE", "POSTIVIE",
    "POSITVE", "POS", "PRESENT",
)
_INVALID = ("INVALID", "ERROR", "REJECTED", "NO SAMPLE", "QNS")
_INDETERMINATE = ("INCONCLUSIVE", "INDETERMINATE", "EQUIVOCAL", "PENDING")


def classify(raw: str):
    """A free-text laboratory result -> Positive, Negative, Invalid,
    Indeterminate, or None when it says nothing either way.

    Only the leading clause is read. An Xpert result reads
    'MTB DETECTED MEDIUM,RIF resistance NOT DETECTED': the first clause is the
    answer to 'was TB found', and the second answers a different question
    entirely - see rifampicin_resistant below."""
    if raw is None:
        return None
    lead = _normalise(str(raw).split(",")[0])
    if not lead:
        return None

    # A bare number is a measurement, not a verdict. CD4 counts and parasite
    # densities arrive this way, as do the '0' placeholders the HIV serology
    # sub-assays are filled with when the assay was not run.
    if re.fullmatch(r"[<>]?\s*\d+(\.\d+)?", lead):
        return None

    for tokens, verdict in ((_INVALID, INVALID), (_INDETERMINATE, INDETERMINATE),
                            (_NEGATIVE, NEGATIVE), (_POSITIVE, POSITIVE)):
        if any(_contains(lead, t) for t in tokens):
            return verdict
    return None


def _contains(lead: str, token: str) -> bool:
    """Whole-token match. A plain substring test would read POS inside
    POSTPARTUM and NEG inside NEGLECT, and the short abbreviations are exactly
    the ones a hurried entry is most likely to use. The token is escaped
    because 'MPS + SEEN' contains a plus, which a regex would otherwise read as
    a quantifier."""
    return re.search(r"(?<![A-Z0-9])" + re.escape(token) + r"(?![A-Z0-9])", lead) is not None


def rifampicin_resistant(raw: str):
    """Xpert reports TB and rifampicin resistance in one string. True, False,
    or None when the result does not speak to resistance.

    'MTB DETECTED MEDIUM,RIF resistance NOT DETECTED' is a TB case that is NOT
    resistant - reading the whole string with classify() would be wrong in both
    directions, which is why resistance has its own reader."""
    if raw is None:
        return None
    parts = str(raw).split(",")
    if len(parts) < 2:
        return None
    tail = _normalise(parts[1])
    if "RIF" not in tail and "RESISTAN" not in tail:
        return None
    if "NOT DETECTED" in tail or "NOT SEEN" in tail:
        return False
    if "DETECTED" in tail or "RESISTANT" in tail:
        return True
    return None


def parasite_grade(raw: str):
    """Malaria microscopy is graded +, ++ or +++. Returns 1, 2, 3 for a
    positive smear, 0 for a negative one, None if it is neither."""
    verdict = classify(raw)
    if verdict == NEGATIVE:
        return 0
    if verdict != POSITIVE:
        return None
    plus = re.search(r"\++", str(raw))
    return len(plus.group(0)) if plus else 1


def reportable_subtest(test_code: str):
    """The analyte whose Result answers the clinical question, or None if this
    test is not one the HMIS forms ask about."""
    entry = LAB_TESTS.get(str(test_code or "").strip())
    return entry["subtest"] if entry else None


def concept(test_code: str):
    entry = LAB_TESTS.get(str(test_code or "").strip())
    return entry["concept"] if entry else None


def is_numeric_test(test_code: str) -> bool:
    return bool(LAB_TESTS.get(str(test_code or "").strip(), {}).get("numeric"))


def numeric_value(raw: str):
    """A measurement, for CD4 and viral load. Returns a float, or None.

    A threshold result - '< 200', the form CD4 is reported in when below the
    limit of quantification - returns the threshold itself; a caller that cares
    about the distinction should read the raw string."""
    if raw is None:
        return None
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(raw).replace(",", ""))
    return float(m.group(0)) if m else None


def summarise(rows: list) -> dict:
    """Count classified results by concept and verdict.

    `rows` are dicts with test_code, subtest_code and result - the shape a
    read of LabResultsEXT produces. Rows for an analyte that is not the
    reportable one are skipped, so a full blood count's twenty-four analytes
    contribute nothing and a malaria smear contributes once."""
    out = {}
    for r in rows or []:
        code = str(r.get("test_code") or "").strip()
        want = reportable_subtest(code)
        if not want:
            continue
        if str(r.get("subtest_code") or "").strip().lower() != want.lower():
            continue
        verdict = classify(r.get("result"))
        if verdict is None:
            continue
        bucket = out.setdefault(concept(code), {POSITIVE: 0, NEGATIVE: 0,
                                                INVALID: 0, INDETERMINATE: 0})
        bucket[verdict] += 1
    return out
