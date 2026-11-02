"""Offline checks for the 105:01 emergency section (ES01, ES07, ES08, ES09).

The rules themselves can only be exercised against ClinicMaster; what can be
held here is everything around them: that every line the extract emits is a
real element on the form's age-and-sex grid, that the compiler writes it where
the form draws it, that the generated SQL is read-only and returns no patient
row, and that the classification cannot leave a case uncounted or count it
twice.

    python scripts/test_emergency.py
"""
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import compiler, emergency as em, extract_scripts as gen, metadata  # noqa: E402
from _lib.validators import mapping  # noqa: E402

# Offline: the committed element listing stands in for the DHIS2 fetch, with the
# category combinations the code itself declares.
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
age_sex = m["categoryCombos"]["OPD_AGE_SEX"]

print("\nEvery line the extract emits is a real 105:01 element on the age-and-sex grid")
# The live form (data entry form ONHrPgcJfZI, read 2 November 2026) draws
# ES01a-d, ES07a-b, ES08a-e and ES09a-d. ES09c_2019, f, g and ES10_2019 exist as
# elements but are not on the form, so nothing is written to them.
check("the codes are the form's", em.codes(),
      ["ES01a", "ES01b", "ES01c", "ES01d", "ES07a", "ES07b",
       "ES08a", "ES08b", "ES08c", "ES08d", "ES08e", "ES09a", "ES09b", "ES09c", "ES09d"])
for code in em.codes():
    de = idx.get(code)
    check(f"{code} is in the code index", de is not None, True)
    if de:
        check(f"{code} is disaggregated by OPD age and sex",
              des[de]["categoryCombo"], age_sex["id"])

print("\nThe compiler writes a marked ES row to its element, by age band and sex")
rows = [
    {"diagnosis": gen.DIRECT_PREFIX + "ES01d", "age_band": "20+Yrs", "sex": "Male",
     "visit_type": "New", "weight": 7, "in_period": True, "count_attendance": False},
    {"diagnosis_code": gen.DIRECT_PREFIX + "ES08b", "age_band": "10-19Yrs", "sex": "Female",
     "visit_type": "New", "weight": 3, "in_period": True, "count_attendance": False},
]
# compile_opd_strata reads diagnosis_code; the upload path renames the column.
for r in rows:
    r.setdefault("diagnosis_code", r.pop("diagnosis", None))
values, unmapped = compiler.compile_opd_strata(rows, "202610")
got = {(v["dataElement"], v["categoryOptionComboName"], v["value"]) for v in values}
check("ES01d, 20+ male, 7", (idx["ES01d"], "20+Yrs, Male", "7") in got, True)
check("ES08b, 10-19 female, 3", (idx["ES08b"], "10-19Yrs, Female", "3") in got, True)
check("nothing falls to All others", [u for u in unmapped], [])
check("and nothing is counted as an attendance",
      [v for v in values if v["dataElement"] in (m["keyDataElements"]["OA01_newAttendance"],
                                                 m["keyDataElements"]["OA02_reAttendance"])], [])

strata = gen.opd_strata_sql(date(2026, 10, 1), date(2026, 11, 1))
raw = gen.opd_sql(date(2026, 10, 1), date(2026, 11, 1))

print("\nThe section is in every flavour of the generated script")
for name, sql in (("SQL only", strata), ("Python and PowerShell", raw)):
    check(f"{name}: ES01 by category", f"'{gen.DIRECT_PREFIX}ES01' + c.cat" in sql, True)
    check(f"{name}: ES08 by road user", f"'{gen.DIRECT_PREFIX}ES08' + c.mode" in sql, True)
    check(f"{name}: ES07a and ES07b",
          all(f"'{gen.DIRECT_PREFIX}{c}'" in sql for c in ("ES07a", "ES07b")), True)
    check(f"{name}: ES09 by category", f"'{gen.DIRECT_PREFIX}ES09' + c.cat" in sql, True)
for os_key in ("windows", "linux", "macos", "sql"):
    _, text = gen.generate("OPD", "202610", os_key, "Monthly", "105:01")
    check(f"{os_key}: the generated file carries the section",
          f"'{gen.DIRECT_PREFIX}ES01' + c.cat" in text, True)

print("\nOne case, one category: ES01a-d add up to the casualty visits")
cat_case = strata[strata.index("END AS cat") - 4000:strata.index("END AS cat")]
cat_case = cat_case[cat_case.rindex("CASE WHEN x.rti = 1"):]
check("the categories are tested in the documented order, RTI first",
      [m_.group(1) for m_ in re.finditer(r"THEN '([a-d])'", cat_case)], ["d", "b", "c"])
check("and everything else is medical", cat_case.rstrip().endswith("ELSE 'a'"), True)
mode_case = strata[strata.index("CASE WHEN x.rti = 0 THEN NULL"):strata.index("END AS mode")]
check("road users: pedestrian, bicycle, motor cycle, motor vehicle, then other",
      [m_.group(1) for m_ in re.finditer(r"THEN '([a-e])'", mode_case)]
      + re.findall(r"ELSE '([a-e])'", mode_case), ["d", "c", "b", "a", "e"])
check("ES08 only for RTI cases", "CASE WHEN c.rti = 1 THEN" in strata, True)
check("ES07b only where ES07a", "c.haem = 1 AND c.ctrl = 1" in strata, True)

print("\nObstetrics and gynaecology only where the form draws the box")
# ES01b has boxes for women of 10-19 and 20+ only.
check("women only", "p.GenderID = '15F'" in strata, True)
check("aged ten or more", "DATEDIFF(day, p.BirthDate, x.VisitDate) >= 3653" in strata, True)

print("\nDeaths at the unit: within a day of arriving at casualty")
# The first rule asked for a casualty-ward bed and no WardTransfer row. Neither
# holds at Jinja: every admission's first WardTransfer row is its own placement,
# and since September casualty books beds on destination wards. It found 0-3
# deaths a month where the register holds 1-12 within a day of arrival.
died = strata[strata.index("AS ctrl,"):strata.index("END AS died")]
check("the death register, on the arrival day or the next",
      "dbo.Deaths dt" in died and "DATEADD(day, 2, CAST(x.VisitDate AS date))" in died, True)
check("or the visit's admission discharged Deceased within the same window",
      f"ds.DischargeStatusID = '{em.DECEASED}'" in died
      and "ds.DischargeDateTime < DATEADD(day, 2" in died, True)
check("where the bed was booked is not used", em.EMERGENCY_WARD in died, False)
check("nor WardTransfer, whose first row is the admission itself", "WardTransfer" in strata, False)
check("free text is not used to find deaths", "DIED" in strata, False)

print("\nEye-ward beds are not a surgical signal")
check("the surgical wards are the surgical and orthopaedic wards only",
      em.SURGICAL_WARDS, ("4004", "4005", "4010"))

print("\nBleeding: negations removed before looking")
check("'no bleeding' is struck out first",
      strata.index("'NO BLEEDING', ' '") < strata.index("AS tb"), True)
check("and the external-bleeding test reads the cleaned text", "x.tb LIKE '%LACERAT%'" in strata, True)
check("nose, gut and vaginal bleeding are not external haemorrhage",
      [t for t in em.EXTERNAL_BLEED_TERMS if re.search(r"NOSE|EPISTAX|GI |VAGIN|PV ", t)], [])

print("\nRead-only, aggregate, and the casualty department named once")
for word in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "EXEC", "MERGE"):
    check(f"no {word}", re.search(rf"\b{word}\b", strata, re.I) is not None, False)
es_branch = strata[strata.rindex("SELECT  es.code AS diagnosis"):]
check("the ES branch returns the five upload columns",
      re.findall(r"AS (\w+)", es_branch[:es_branch.index("FROM")]), ["diagnosis", "sex", "visit", "n"])
check("and groups", "GROUP BY es.code, bd.band, sx.name" in es_branch, True)
check("no patient number, name or date of birth comes back",
      re.search(r"PatientNo|FullName|BirthDate", es_branch[:es_branch.index("FROM")]) is not None, False)
check("casualty is the same department the attendance rule names",
      em.EMERGENCY_COMMUNITIES, gen.ENTRY_POINT_COMMUNITIES)
check("every pattern is free of quotes",
      [t for t in (em.RTI_TERMS + em.VEHICLE_TERMS + em.OBS_TERMS + em.SURGICAL_TERMS
                   + em.EXTERNAL_BLEED_TERMS + em.CONTROLLED_TERMS + em.NOT_BLEEDING) if "'" in t], [])
check("each emergency CTE is built once: the classification is read by one branch",
      strata.count("FROM    ecls c"), 1)

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
