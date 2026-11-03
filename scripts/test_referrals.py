"""Offline checks for 105:01 OR01 (Referrals to unit) and OR02 (Referrals from
unit).

The rules can only be exercised against ClinicMaster; what is held here is
everything around them: that both lines are real elements on the form's
age-and-sex grid, that the compiler writes them there and not to All others,
that every flavour of the generated script carries them, over the same visits
as the attendance, read-only and returning no patient row.

    python scripts/test_referrals.py
"""
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import compiler, extract_scripts as gen, metadata, referrals as rf  # noqa: E402
from _lib.validators import mapping  # noqa: E402

with open(os.path.join(HERE, "..", "api", "_lib", "dhis2_mapping.json")) as _f:
    _listing = json.load(_f)
metadata._MAPPING = {**metadata.CONSTANTS,
                     "dataElements": _listing["dataElements"],
                     "HMIS105_01_codeIndex": _listing["HMIS105_01_codeIndex"],
                     "HMIS108_codeIndex": _listing["HMIS108_codeIndex"]}

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


m = mapping()
idx = m["HMIS105_01_codeIndex"]
des = m["dataElements"]["HMIS105_01"]

print("\nBoth lines are real 105:01 elements on the age-and-sex grid")
check("the codes", rf.codes(), ["OR01", "OR02"])
for code in rf.codes():
    check(f"{code} is in the code index", code in idx, True)
    check(f"{code} is disaggregated by OPD age and sex",
          des[idx[code]]["categoryCombo"], m["categoryCombos"]["OPD_AGE_SEX"]["id"])

print("\nThe compiler writes a marked OR row to its element")
rows = [
    {"diagnosis_code": gen.DIRECT_PREFIX + "OR01", "age_band": "20+Yrs", "sex": "Female",
     "visit_type": "New", "weight": 11, "in_period": True, "count_attendance": False},
    {"diagnosis_code": gen.DIRECT_PREFIX + "OR02", "age_band": "29Dys-4Yrs", "sex": "Male",
     "visit_type": "Re", "weight": 2, "in_period": True, "count_attendance": False},
]
values, unmapped = compiler.compile_opd_strata(rows, "202610")
got = {(v["dataElement"], v["categoryOptionComboName"], v["value"]) for v in values}
check("OR01, 20+ female, 11", (idx["OR01"], "20+Yrs, Female", "11") in got, True)
check("OR02, 29 days-4 years male, 2", (idx["OR02"], "29Dys-4Yrs, Male", "2") in got, True)
check("nothing falls to All others", dict(unmapped), {})
check("and nothing is counted as an attendance",
      [v for v in values if v["dataElement"] in (m["keyDataElements"]["OA01_newAttendance"],
                                                 m["keyDataElements"]["OA02_reAttendance"])], [])

strata = gen.opd_strata_sql(date(2026, 10, 1), date(2026, 11, 1))
raw = gen.opd_sql(date(2026, 10, 1), date(2026, 11, 1))

print("\nEvery flavour of the generated script carries both lines")
for name, sql in (("SQL only", strata), ("Python and PowerShell", raw)):
    check(f"{name}: OR01", f"'{gen.DIRECT_PREFIX}OR01'" in sql, True)
    check(f"{name}: OR02", f"'{gen.DIRECT_PREFIX}OR02'" in sql, True)
for os_key in ("windows", "linux", "macos", "sql"):
    _, text = gen.generate("OPD", "202610", os_key, "Monthly", "105:01")
    check(f"{os_key}: the generated file carries OR01 and OR02",
          all(f"'{gen.DIRECT_PREFIX}{c}'" in text for c in rf.codes()), True)

DB = "ClinicMasterMOH"
OCT = (date(2026, 10, 1), date(2026, 11, 1))
cte_s = rf.ctes(DB, *OCT, "s")
cte_b = rf.ctes(DB, *OCT, "b")
or_strata = cte_s + "\n" + rf.strata_select(gen.DIRECT_PREFIX)
or_raw = cte_b + "\n" + rf.raw_select(gen.DIRECT_PREFIX)

print("\nThe generated scripts carry the rules as written here")
check("SQL only: the referral CTEs follow the attendance CTE s", (",\n" + cte_s) in strata, True)
check("SQL only: and the branch reads them", rf.strata_select(gen.DIRECT_PREFIX) in strata, True)
check("scripts: the referral CTEs follow the attendance CTE b", (",\n" + cte_b) in raw, True)
check("scripts: and the branch reads them", rf.raw_select(gen.DIRECT_PREFIX) in raw, True)
check("the CTEs come after every CTE they read",
      strata.index("), s AS (") < strata.index("ori AS (") and raw.index("), b AS (") < raw.index("ori AS ("), True)

print("\nOver the OPD attendances themselves, one per visit")
check("SQL only: flagged over s, the attendance CTE", "    FROM    s\n    LEFT JOIN ori ON ori.VisitNo = s.VisitNo" in cte_s, True)
check("scripts: flagged over b, the attendance CTE", "    FROM    b\n    LEFT JOIN ori ON ori.VisitNo = b.VisitNo" in cte_b, True)
check("the notes read are those of these attendances",
      cte_s.count("FROM    s\n            JOIN    ClinicMasterMOH.dbo."), 2)
check("an attendance with several referral forms counts once", "SELECT  DISTINCT er.VisitNo" in cte_s, True)
check("and one with several referral notes counts once", "SELECT  DISTINCT nt.VisitNo" in cte_s, True)
check("one pass makes both lines", rf.strata_select(gen.DIRECT_PREFIX).count("FROM    orf f"), 1)
check("each line once per attendance, never per form or note",
      rf.strata_select(gen.DIRECT_PREFIX).count("COUNT(*)"), 1)
check("every lookup is a set joined once, not a lookup per visit",
      ("OUTER APPLY" in cte_s, "EXISTS" in cte_s), (False, False))

print("\nThe rules: referred in")
check("referred in means visit category 10R, Refferal", rf.REFERRAL_IN_CATEGORIES, ("10R",))
check("read from the visits of the period",
      "WHERE   rv.VisitDate >= '2026-10-01'\n      AND   rv.VisitDate <  '2026-11-01'" in cte_s, True)
for cat, name in (("10RP", "Represented"), ("10RTT", "Return To Treatment"), ("10S", "Self Request")):
    check(f"{cat} ({name}) is not a referral", f"'{cat}'" in or_strata, False)
check("a 10R visit whose referrer is SELF is not counted",
      "UPPER(LTRIM(RTRIM(ISNULL(rv.ReferredBy, '')))) NOT LIKE 'SELF%'" in cte_s, True)

print("\nThe rules: referred out")
check("an external referral form counts", "FROM    ClinicMasterMOH.dbo.ExternalReferrals er" in cte_s, True)
check("the notes read are the clinician's four fields and the triage notes",
      (all(f"CAST(c.{f} AS nvarchar({rf.NOTE_CHARS}))" in cte_s for f in rf.NOTE_FIELDS)
       and f"CAST(tg.Notes AS nvarchar({rf.NOTE_CHARS}))" in cte_s), True)
check("as ordinary text, never as a large object", "nvarchar(max)" in or_strata, False)
check("a referral to a specialist inside JRRH is not counted",
      re.search(r"\bdbo\.Referrals\b", or_strata) is not None, False)
check("only notes that mention a referral or transfer are searched",
      "WHERE   n.t LIKE '%REF%' OR n.t LIKE '%TRANSF%'" in cte_s, True)
check("and every phrase is a referral or a transfer",
      all("REF" in p or "TRANSF" in p for p in rf.OUT_PHRASES), True)
check("the destination must sit within the window after the phrase",
      f"SUBSTRING(nt.t, ph.p, {rf.WINDOW})" in cte_s, True)
check("the window stops at the end of the note",
      "LEFT(w0.w, CHARINDEX('|', w0.w) - 1)" in cte_s, True)
check("and at the first FROM",
      "LEFT(w1.w, CHARINDEX(' FROM ', w1.w) - 1)" in cte_s, True)
check("every destination is looked for in the cut window",
      all(f"w2.w LIKE '%{d}%'" in cte_s for d in rf.DESTINATIONS), True)
check("every phrase is looked for", all(f"CHARINDEX('{p}', nt.t)" in cte_s for p in rf.OUT_PHRASES), True)
check("OR02 is the form or the notes",
      "(CASE WHEN f.or02_form = 1 OR f.or02_note = 1 THEN '(hmis)OR02' END)" in or_strata, True)
for inside in ("JRRH", "JINJA", "PHYSIO", "DENTAL", "ENT ", "SURGICAL OPD", "CLINIC", "REGIONAL"):
    check(f"{inside.strip()} is not an outside destination",
          any(inside in d or d.strip() in inside for d in rf.DESTINATIONS), False)


def note_rule(text):
    """The notes rule in Python, step for step with the SQL: the first place
    each phrase occurs in the note, a window of WINDOW characters cut at the
    end of the note and at the first FROM, then any destination."""
    t = " " + text.upper() + " "
    for p in rf.OUT_PHRASES:
        i = t.find(p)
        if i < 0:
            continue
        w = t[i:i + rf.WINDOW] + "|"
        w = w[:w.index("|")] + " FROM "
        w = w[:w.index(" FROM ")]
        if any(d in w for d in rf.DESTINATIONS):
            return True
    return False


print("\nThe notes rule on the wording found in JRRH's OPD notes, June to October 2026")
for text, want in (
        ("Referred to Mulago for urgent surgery", True),
        ("Referral to UCI", True),
        ("For referral to ped surgery in Mulago", True),
        ("Refer to CORSU hand surgery", True),
        ("Referral to MNHR", True),
        ("Referral to Kiruddu | fracture distal 1/3 tibia", True),
        ("Refer to orthopedic surgeons in Mulago", True),
        ("Refer to physiotherapy", False),
        ("Refer to ENT", False),
        ("Referred to OPD for mngnt of HTN", False),
        ("Refer to gyn clinic | 28/F with left breast pain, from Mulago", False),
        ("Referred to the hospital from Kakira sugar co", False),
        ("Referred to JRRH | consult from OMF surgeon", False),
        ("Referred to JRRH from Mulago", False),
        ("Referred from Mulago NRH", False),
        ("Seen in Mulago last year, review", False),
):
    check(f"{text!r}", note_rule(text), want)

print("\nThe record-level query for checking a live run")
rec = rf.records_select()
check("reads the same flags the upload rows are made from", "FROM    orf f" in rec, True)
check("returns flags and counts only",
      rec.split("\n")[0], "SELECT  f.band, f.sex, f.visit, f.or01, f.or02_form, f.or02_note, COUNT(*) AS n")
check("no patient number or name", re.search(r"PatientNo|FullName|BirthDate", rec) is not None, False)

print("\nRead-only and aggregate")
for word in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "EXEC", "MERGE"):
    check(f"no {word}", re.search(rf"\b{word}\b", or_strata, re.I) is not None, False)
check("the branch returns the five upload columns",
      rf.strata_select(gen.DIRECT_PREFIX).split("\n")[0],
      "SELECT  rc.code AS diagnosis, f.band, f.sex, f.visit, COUNT(*) AS n")
check("and the scripts' branch the five columns they read",
      rf.raw_select(gen.DIRECT_PREFIX).split("\n")[0],
      "SELECT  f.age_years, f.sex, f.visit_category, rc.code AS diagnosis, COUNT(*) AS n")
check("no patient number, name, date of birth or referral text comes back",
      re.search(r"PatientNo|FullName|BirthDate|ReferredBy|ReferredTo|nt\.t",
                rf.strata_select(gen.DIRECT_PREFIX) + rf.raw_select(gen.DIRECT_PREFIX)) is not None, False)

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
