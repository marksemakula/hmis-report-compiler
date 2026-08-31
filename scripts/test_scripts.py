"""Offline checks for the generated extraction scripts.

A script handed to someone on the hospital network is code we will never see
run. Three things therefore have to be true before it leaves here:

  1. It must be syntactically valid. The generated Python is compiled below;
     a template that produces a SyntaxError would fail in front of a user with
     no way to diagnose it.
  2. Its age banding must match the server's, or the connector and the upload
     path report different numbers for the same month.
  3. The period must be baked in, so a script downloaded for June cannot be run
     against May.

    python scripts/test_scripts.py
"""
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import compiler as srv, extract_scripts as gen, periods  # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


print("\nBanding rules must match the compiler exactly")
check("band table identical to the server", gen.BAND_RULES, srv.OPD_BANDS)

print("\nGeneration for each platform")
made = {}
for os_key in ("windows", "macos", "linux"):
    name, text = gen.generate("OPD", "202606", os_key, "Monthly", "105:01")
    made[os_key] = (name, text)
    ext = gen.OS_CHOICES[os_key]["ext"]
    check(f"{os_key}: filename", name, f"jrrh_extract_opd_202606.{ext}")
    check(f"{os_key}: not empty", len(text) > 800, True)
    check(f"{os_key}: names the report", "105:01" in text, True)
    check(f"{os_key}: names the period in words", "June 2026" in text, True)
    check(f"{os_key}: output filename", gen.output_name("OPD", "202606") in text, True)
    check(f"{os_key}: warns to use a read-only login",
          "read-only" in text.lower() or "readonly" in text.lower(), True)

print("\nThe period is baked in, not a parameter the user can get wrong")
_, june = made["linux"]
check("June start date present", "'2026-06-01'" in june, True)
check("exclusive end is 1 July", "'2026-07-01'" in june, True)
june_sql = june[june.index("SELECT"):june.index("GROUP BY")]
check("no other month leaks into the SQL",
      any(m in june_sql for m in ("2026-05-", "2026-04-", "2026-08-")), False)
_, feb = gen.generate("OPD", "202402", "linux", "Monthly", "105:01")
check("leap February ends on the 29th", "'2024-03-01'" in feb, True)
_, dec = gen.generate("OPD", "202612", "linux", "Monthly", "105:01")
check("December rolls into the next year", "'2027-01-01'" in dec, True)

print("\nThe generated Python must actually be valid Python")
for os_key in ("macos", "linux"):
    name, text = made[os_key]
    try:
        compile(text, name, "exec")
        check(f"{os_key}: compiles", True, True)
    except SyntaxError as exc:
        check(f"{os_key}: compiles", f"SyntaxError line {exc.lineno}: {exc.msg}", True)

print("\nThe generated Python's banding must agree with the server's")
ns = {}
exec(compile(made["linux"][1].replace('if __name__ == "__main__":\n    main()', ''),
             "generated", "exec"), ns)
ages = [0, 1 / 365, 28 / 365, 29 / 365, 1, 4.99, 5, 9.99, 10, 19.99, 20, 45, 130]
check(f"{len(ages)} ages band identically",
      [a for a in ages if ns["band"](a) != srv.opd_band(a)], [])
check("generated re-attendance set matches",
      ns["RE_ATTENDANCE"], set(gen.RE_ATTENDANCE))

print("\nPowerShell shape")
ps = made["windows"][1]
check("queries through .NET, needs nothing installed",
      "System.Data.SqlClient.SqlConnection" in ps, True)
check("password is read as a secure string", "-AsSecureString" in ps, True)
check("password is not a plain parameter default", 'param(\n    [string]$Password' in ps, False)
check("writes CSV", "Export-Csv" in ps, True)
check("every band label appears",
      all(label in ps for _, label in gen.BAND_RULES), True)
check("re-attendance categories appear",
      all(c in ps for c in gen.RE_ATTENDANCE), True)

print("\nThe SQL must be read-only and aggregate")
sql = gen.opd_sql(date(2026, 6, 1), date(2026, 7, 1))
for word in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "EXEC"):
    check(f"no {word}", re.search(rf"\b{word}\b", sql, re.I) is not None, False)
check("groups rather than listing rows", "GROUP BY" in sql, True)
check("new vs re is decided by first visit in the period, per the Ministry rule",
      "ROW_NUMBER() OVER (PARTITION BY vv.PatientNo" in sql, True)
check("the visit category no longer decides attendance",
      "VisitCategoryID" in sql, False)
# What matters is the shape of what comes BACK, not which columns the
# computation reads. BirthDate is read to derive an age; it is never returned.
# The query opens with a CTE, so the OUTER select is the one that matters.
outer = sql.split(")\nSELECT", 1)[1] if ")\nSELECT" in sql else sql[sql.index("SELECT"):]
select_list = outer[:outer.index("FROM")]
returned = re.findall(r"AS\s+(\w+)", select_list)
check("returns exactly four aggregate columns", returned,
      ["age_years", "sex", "visit_category", "n"])
check("nothing identifying is returned",
      [c for c in returned if re.search(
          r"name|patient|clinic|nationalid|birth|phone|address|visitno", c, re.I)], [])
check("BirthDate is read but not returned",
      ("BirthDate" in select_list, "BirthDate" in " ".join(returned)), (True, False))
check("PatientNo is never returned", "PatientNo" in select_list, False)
check("counts", "COUNT(*)" in sql, True)

print("\nRefusals")
def refuses(fn, fragment):
    try:
        fn()
        return False
    except ValueError as exc:
        return fragment in str(exc)

check("unknown operating system",
      refuses(lambda: gen.generate("OPD", "202606", "solaris", "Monthly", "x"),
              "Unknown operating system"), True)
check("report with no script yet",
      refuses(lambda: gen.generate("IPD", "202606", "linux", "Monthly", "108"),
              "No extraction script exists"), True)
check("malformed period",
      refuses(lambda: gen.generate("OPD", "2026Q9", "linux", "Monthly", "105:01"),
              "not a valid"), True)

print("\nRecognising a strata file on upload")
check("exact columns", gen.looks_like_strata(["diagnosis", "band", "sex", "visit", "n"]), True)
check("order does not matter", gen.looks_like_strata(["n", "sex", "visit", "band", "diagnosis"]), True)
check("case and spacing tolerated",
      gen.looks_like_strata(["Diagnosis", " Band ", "SEX", "Visit", "N"]), True)
check("extra columns still recognised",
      gen.looks_like_strata(["diagnosis", "band", "sex", "visit", "n", "notes"]), True)
check("a register extract is not strata",
      gen.looks_like_strata(["PatientNo", "VisitDate", "Age", "Sex", "DiagnosisCode"]), False)
check("a partial match is not strata", gen.looks_like_strata(["diagnosis", "n"]), False)
check("empty headers", gen.looks_like_strata([]), False)
check("no headers", gen.looks_like_strata(None), False)

print("\nThe header row the scripts write matches what upload expects")
for os_key in ("windows", "linux"):
    text = made[os_key][1]
    check(f"{os_key}: emits all five columns",
          all(c in text for c in gen.strata_columns()), True)

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
