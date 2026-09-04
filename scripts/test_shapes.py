"""Offline checks that an upload is matched to the right report.

Week 35 of 2026 was compiled into nothing because its 033B tally was uploaded
with 105:01 and July 2026 selected. The upload read seventeen rows, called all
seventeen invalid, and printed the same sentence seventeen times:

    PatientNo is required; Age is required; Sex is required;
    DiagnosisCode is required; VisitDate is required; VisitType is required

Every word of that is true and none of it is useful. The file is a two-column
tally; it was never going to have a PatientNo. Validation was being asked "is
this row usable" when the question was "is this the right file", and asked the
wrong question it repeats itself once per row.

These checks pin the answer to the right question: recognise the shape first,
say once what the file is, and name the report and the period it belongs to.

    python scripts/test_shapes.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import metadata  # noqa: E402

metadata._MAPPING = {
    **metadata.CONSTANTS,
    "dataElements": {"HMIS105_01": {}, "HMIS108": {}, "HMIS033B": {}},
    "HMIS105_01_codeIndex": {},
    "HMIS108_codeIndex": {},
    "HMIS033B_codeIndex": {},
}

from _lib import extract_scripts, validators  # noqa: E402
from _lib.surveillance import SURV_COLUMNS  # noqa: E402
from _lib.validators import (  # noqa: E402
    FILE_SHAPES, IPD_COLUMNS, OPD_COLUMNS, identify_shape, period_hint,
    shape_mismatch,
)

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


def check_in(label, needle, haystack):
    if needle.lower() not in str(haystack).lower():
        failures.append(f"{label}\n     expected to contain: {needle!r}\n"
                        f"     actual:   {haystack!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


def check_not_in(label, needle, haystack):
    if needle.lower() in str(haystack).lower():
        failures.append(f"{label}\n     expected NOT to contain: {needle!r}\n"
                        f"     actual:   {haystack!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


def rows(header, *values):
    return [dict(zip(header, v)) for v in values]


# The week-35 file as the extraction script writes it: metadata rows first,
# then the tally. This is the exact upload that produced seventeen errors.
WEEK35 = rows(
    ["Code", "Value"],
    ("_start_yyyymmdd", "20260824"), ("_end_yyyymmdd", "20260830"),
    ("_days_covered", "7"), ("_req_rdt", "173"), ("_req_smear", "88"),
    ("_req_xpert", "21"),
    ("AP01", "3619"), ("AP02", "3619"), ("GP01", "21"), ("GP02", "21"),
    ("GP03", "4"), ("GP04", "0"), ("GP05", "0"),
    ("MA02", "0"), ("MA03", "0"), ("MA04", "88"), ("MA05", "0"),
)

JULY_LINE_LIST = rows(
    OPD_COLUMNS,
    ("P0001", "2026-07-03", "34", "Years", "F", "EP01c", "New"),
    ("P0002", "2026-07-14", "2", "Years", "M", "EP02", "New"),
    ("P0003", "2026-08-01", "51", "Years", "M", "MH26", "Re"),
)

IPD_LINE_LIST = rows(
    IPD_COLUMNS,
    ("A0001", "2026-07-02", "2026-07-09", "44", "Years", "F", "Female Medical",
     "CD01", "Discharged"),
    ("A0002", "2026-07-20", "", "7", "Years", "M", "Paediatrics", "CD02", ""),
)

STRATA = rows(
    extract_scripts.strata_columns(),
    ("EP01c", "20+Yrs", "F", "New", "41"),
    ("EP01c", "5-9Yrs", "M", "Re", "12"),
)

print("\n-- the signatures match the templates they claim to recognise --")
# The signatures are written out rather than imported so the module stays free
# of surveillance and extract_scripts. These four checks are what stops that
# convenience turning into drift.
SIGNATURES = dict((shape, sig) for shape, sig in FILE_SHAPES)


def lowered(names):
    return {str(n).strip().lower() for n in names}


check("SURV signature is a subset of the 033B template columns",
      SIGNATURES["SURV"].issubset(lowered(SURV_COLUMNS)), True)
check("STRATA signature matches the generated script's columns",
      SIGNATURES["STRATA"], lowered(extract_scripts.strata_columns()))
check("OPD signature is a subset of the 105:01 template columns",
      SIGNATURES["OPD"].issubset(lowered(OPD_COLUMNS)), True)
check("IPD signature is a subset of the 108 template columns",
      SIGNATURES["IPD"].issubset(lowered(IPD_COLUMNS)), True)

print("\n-- each template is recognised as its own report --")
check("033B tally", identify_shape(SURV_COLUMNS), "SURV")
check("033B template with its Label column",
      identify_shape(["Code", "Label", "Value"]), "SURV")
check("105:01 line list", identify_shape(OPD_COLUMNS), "OPD")
check("108 line list", identify_shape(IPD_COLUMNS), "IPD")
check("script strata", identify_shape(extract_scripts.strata_columns()), "STRATA")
check("strata is recognised by looks_like_strata too, unchanged",
      extract_scripts.looks_like_strata(extract_scripts.strata_columns()), True)

print("\n-- spelling of the headers does not matter --")
check("spaces in headers", identify_shape(["Patient No", "Visit Date", "Age"]), "OPD")
check("upper case", identify_shape(["CODE", "VALUE"]), "SURV")
check("collapsed raw EMR export keeps the OPD shape",
      identify_shape(["PatientNo", "Age", "AgeUnit", "Sex", "VisitDate",
                      "VisitType", "DiagnosisCode", "CountAttendance"]), "OPD")

print("\n-- an unfamiliar file is left to the per-row messages --")
check("unknown columns", identify_shape(["Ward", "Beds", "Occupancy"]), None)
check("no columns at all", identify_shape([]), None)
check("None", identify_shape(None), None)

print("\n-- the file says which period it covers --")
check("033B tally reads _start_yyyymmdd", period_hint("SURV", WEEK35), "2026W35")
check("a tally with no metadata rows offers no period",
      period_hint("SURV", rows(["Code", "Value"], ("AP01", "12"))), None)
check("105:01 line list takes the modal month, not the stray August row",
      period_hint("OPD", JULY_LINE_LIST), "202607")
check("108 line list reads AdmissionDate", period_hint("IPD", IPD_LINE_LIST), "202607")
check("undated rows offer no period",
      period_hint("OPD", rows(["PatientNo", "VisitDate"], ("P1", ""))), None)
check("compact yyyymmdd dates parse", str(validators._parse_date("20260824")),
      "2026-08-24")
check("an Excel serial still parses", str(validators._parse_date("45870")),
      "2025-08-01")

print("\n-- the right file for the selected report is accepted --")
check("105:01 with a line list", shape_mismatch("OPD", JULY_LINE_LIST), None)
check("105:01 with script strata", shape_mismatch("OPD", STRATA), None)
check("108 with a line list", shape_mismatch("IPD", IPD_LINE_LIST), None)
check("033B with a tally", shape_mismatch("SURV", WEEK35), None)
check("an unrecognised file is not second-guessed",
      shape_mismatch("OPD", rows(["Ward", "Beds"], ("ICU", "8"))), None)
check("no rows at all", shape_mismatch("OPD", []), None)

print("\n-- the wrong file is named, once --")
msg = shape_mismatch("OPD", WEEK35)      # the actual week-35 mis-selection
check("the mis-selection is refused", bool(msg), True)
check_in("says what the file is", "033B tally", msg)
check_in("names the report that was selected", "105:01", msg)
check_in("names the report to select instead", "select 033B", msg)
check_in("carries the week the file covers", "2026w35", msg)
check_in("spells the week out in dates", "24 aug", msg)
check_not_in("does not talk about missing columns", "patientno is required", msg)
check_not_in("no em dash, per the house style", "—", msg)
check("said once, not once per row", msg.count("This file is"), 1)

back = shape_mismatch("SURV", JULY_LINE_LIST)
check("a line list uploaded as 033B is refused", bool(back), True)
check_in("names 105:01 as its report", "select 105:01", back)
check_in("and the month it covers", "july 2026", back)

check_in("108 selected for a 033B tally", "select 033B", shape_mismatch("IPD", WEEK35))
# A file that carries no dates of its own still gets told which cadence to pick.
no_dates = shape_mismatch("SURV", rows(["PatientNo", "VisitDate"], ("P1", "")))
check_in("a dateless line list names the cadence instead", "pick a monthly period",
         no_dates)
check_not_in("and does not invent a period", "period 2026", no_dates)
# Strata used to be accepted whatever the report, so a strata file uploaded as
# 108 was stored as SCRIPT and then compiled by the inpatient compiler, which
# reads columns strata does not have.
strata_as_ipd = shape_mismatch("IPD", STRATA)
check("strata uploaded as 108 is refused", bool(strata_as_ipd), True)
check_in("and points at 105:01", "select 105:01", strata_as_ipd)
check("strata uploaded as 033B is refused", bool(shape_mismatch("SURV", STRATA)), True)

print("\n-- a column is read by what it holds, not how it is spelled --")
# The EMR names the same column differently from one report to the next. Its
# visit report writes "All Diagnosis" and "Visit Category"; its diagnosis report
# writes "Diagnosis" and "Visit Type". Matching one spelling sent a 10,004-row
# July extract straight past the adapter and into validation, which complained
# five times a row about columns the file had all along:
#
#     PatientNo is required; Sex is required; DiagnosisCode is required;
#     VisitDate is required; VisitType is required
#
# Unlike the week-35 case above this file IS the right file for the report, so
# shape_mismatch stays silent - correctly, because the shape is OPD. The fault
# was entirely in the spelling.
CLINICMASTER = ["Visit No", "Patient No", "Reference No", "Gender", "Birth Date",
                "Age", "Age Category", "Surname", "First Name", "Other Name",
                "Visit Date", "Disease Code", "Diagnosis", "Disease Category",
                "Visit Type", "Action Point"]
EMR_VISITS = ["Visit No", "Patient No", "Gender", "Age", "Visit Date",
              "Visit Category", "All Diagnosis"]

check("the diagnosis export is recognised as a raw EMR file",
      validators._is_raw_emr(CLINICMASTER), True)
check("and so is the visit export it used to be the only one of",
      validators._is_raw_emr(EMR_VISITS), True)
check("the clean 105:01 template is left alone",
      validators._is_raw_emr(OPD_COLUMNS), False)
check("so is a 033B tally", validators._is_raw_emr(["Code", "Value"]), False)
check("so is a strata file",
      validators._is_raw_emr(extract_scripts.strata_columns()), False)
check("and so is a 108 extract", validators._is_raw_emr(IPD_COLUMNS), False)

CM_CSV = (
    ",".join(CLINICMASTER) + "\n"
    "V1,1234.0,R1,Female,1990-01-01,36,Adult,A,B,C,2026-07-03 00:00:00,1A00,"
    "MALARIA,Infectious,Consultation,x\n"
    "V1,1234.0,R1,Female,1990-01-01,36,Adult,A,B,C,2026-07-03 00:00:00,CA23,"
    "ASTHMA,Respiratory,Consultation,x\n"
    "V2,999,R2,Male,2000-01-01,26,Adult,D,E,F,2026-07-04 00:00:00,1A00,"
    "MALARIA,Infectious,Follow up,x\n"
).encode()
collapsed = validators.parse_file("105July2026.csv", CM_CSV)

check("two conditions at one visit stay two rows", len(collapsed), 3)
check("the patient number loses its spreadsheet decimal",
      collapsed[0]["PatientNo"], "1234")
check("Gender becomes Sex", collapsed[0]["Sex"], "F")
check("Visit Date becomes VisitDate", collapsed[0]["VisitDate"], "2026-07-03")
check("Diagnosis becomes DiagnosisCode", collapsed[0]["DiagnosisCode"], "MALARIA")
check("Visit Type becomes VisitType", collapsed[0]["VisitType"], "New")
check("and a follow-up is a re-attendance", collapsed[2]["VisitType"], "Re-attendance")
# The Ministry counts every condition recorded, but a visit is one attendance
# however many conditions were recorded at it.
check("the visit is counted once", [r["CountAttendance"] for r in collapsed],
      ["1", "0", "1"])
check("the EMR's own disease code is not mistaken for the HMIS code",
      any(r["DiagnosisCode"] in ("1A00", "CA23") for r in collapsed), False)

# The same tolerance at the validation step, for a file that never went through
# the EMR adapter: what matters is that the required fields are found, not that
# the diagnosis maps - the code index is stubbed empty in these checks.
spelled_differently = rows(
    ["Patient No", "Visit Date", "Age", "AgeUnit", "Gender", "Diagnosis", "Visit Type"],
    ("P0001", "2026-07-03", "34", "Years", "F", "EP01c", "New"),
)
_, spelled_errors = validators.validate_rows("OPD", spelled_differently, "202607")
missing = [p for e in spelled_errors for p in e["problems"] if "is required" in p]
check("no column is called missing when the file spells it differently", missing, [])

# And the week-35 message must not regress into silence: a tally has none of
# these columns under any spelling.
check("a 033B tally still matches nothing", identify_shape(["Code", "Value"]), "SURV")

print("\n-- the route asks before it validates --")
with open(os.path.join(HERE, "..", "api", "index.py")) as f:
    source = f.read()
check("upload calls shape_mismatch", "shape_mismatch(body.report_type, rows)" in source, True)
check("and does so before validate_rows",
      source.index("shape_mismatch(body.report_type, rows)")
      < source.index("validate_rows(body.report_type, rows, period)"), True)

print(f"\n{len(failures)} failed")
for f in failures:
    print(" ", f)
sys.exit(1 if failures else 0)
