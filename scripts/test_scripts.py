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
check("generated sex map uses ClinicMaster's codes",
      ns["SEX_CODES"], gen.SEX_CODES)
check("15F is Female, 15M is Male",
      (ns["SEX_CODES"].get("15F"), ns["SEX_CODES"].get("15M")), ("Female", "Male"))

print("\nPowerShell shape")
ps = made["windows"][1]
check("queries through .NET, needs nothing installed",
      "System.Data.SqlClient.SqlConnection" in ps, True)
check("password is read as a secure string", "-AsSecureString" in ps, True)
check("password is not a plain parameter default", 'param(\n    [string]$Password' in ps, False)
check("writes CSV", "Export-Csv" in ps, True)
check("every band label appears",
      all(label in ps for _, label in gen.BAND_RULES), True)
check("sex codes appear", all(c in ps for c in gen.SEX_CODES), True)
check("does not match on the words Male/Female",
      "'^(f|female)$'" in ps, False)

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
check("returns the aggregate columns only", returned, ["diagnosis", "n"])
check("nothing identifying is returned",
      [c for c in returned if re.search(
          r"name|patient|clinic|nationalid|birth|phone|address|visitno", c, re.I)], [])
check("PatientNo is never returned", "PatientNo" in select_list, False)
check("BirthDate is read to derive an age but never returned",
      ("BirthDate" in sql, "BirthDate" in " ".join(returned)), (True, False))
check("counts", "COUNT(*)" in sql, True)

print("\nThe confirmed ClinicMaster schema, as of 25 August 2026")
check("OPD diagnoses only", "d.VisitType   = 'Out Patient'" in sql, True)
check("polymorphic parent pinned to Visits", "d.ObjectName  = 'Visits'" in sql, True)
check("joins Diagnosis on TreatmentNo, since it has no VisitNo",
      "d.TreatmentNo = b.VisitNo" in sql, True)
check("joins on the ICD-11 code, not the drifting name",
      ("d.DiseaseCode" in sql, "DiseaseName" in sql), (True, False))
check("inpatient episodes excluded from OPD attendance", "'9IP'" in sql, True)
check("two grains: attendance rows and condition rows",
      sql.count("UNION ALL"), 1)
check("attendance sentinel present", "'(attendance)'" in sql, True)

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


# ---------------------------------------------------------------------------
# HMIS 033B weekly surveillance, added 3 September 2026.
#
# 033B is a tally, not a register: its script returns two columns and needs no
# age banding. The codes it emits were checked against the live national
# instance on 3 September 2026 - all twelve resolve, and all 239 of the data
# set's elements parse - so an upload compiled from this script cannot come
# back with an unmapped code.
# ---------------------------------------------------------------------------
print("\n033B weekly surveillance script")
surv = {}
for os_key in ("windows", "macos", "linux"):
    name, text = gen.generate("SURV", "2026W35", os_key, "Weekly", "033B")
    surv[os_key] = text
    check(f"{os_key}: filename carries the week", name,
          f"jrrh_extract_surv_2026W35.{gen.OS_CHOICES[os_key]['ext']}")
    check(f"{os_key}: names the week in words", "Week 35" in text or "24 Aug" in text, True)
    check(f"{os_key}: writes the two-column tally the compiler expects",
          "Code" in text and "Value" in text, True)

for os_key in ("macos", "linux"):
    try:
        compile(surv[os_key], "surv", "exec")
        check(f"{os_key}: compiles", True, True)
    except SyntaxError as exc:
        check(f"{os_key}: compiles", f"SyntaxError line {exc.lineno}", True)

print("\nThe week is ISO-8601 and is baked in")
check("week 35 of 2026 starts Monday 24 August", "'2026-08-24'" in surv["linux"], True)
check("and ends exclusive at 31 August", "'2026-08-31'" in surv["linux"], True)
check("no neighbouring week leaks in",
      any(d in surv["linux"] for d in ("2026-08-17", "2026-09-07")), False)
_, w01 = gen.generate("SURV", "2026W01", "linux", "Weekly", "033B")
check("week 1 of 2026 begins in December 2025, per ISO-8601",
      "'2025-12-29'" in w01, True)
_, w53 = gen.generate("SURV", "2026W53", "linux", "Weekly", "033B")
check("2026 has a week 53", "'2026-12-28'" in w53, True)

print("\nThe surveillance SQL is read-only and returns one grid")
ssql = gen.surv_sql(date(2026, 8, 24), date(2026, 8, 31))
for word in ("UPDATE", "DELETE", "ALTER", "TRUNCATE", "EXEC", "MERGE"):
    check(f"no {word}", re.search(rf"\b{word}\b", ssql, re.I) is not None, False)
check("writes only to temp tables",
      [t for t in re.findall(r"INSERT INTO (\S+)", ssql) if not t.startswith("#")], [])
check("drops only temp tables",
      [t for t in re.findall(r"DROP TABLE (\S+)", ssql) if not t.startswith("#")], [])
check("one result grid", len(re.findall(r"^SELECT Code, Value", ssql, re.M)), 1)

print("\nEvery emitted code is a real 033B element")
# Verified against hmis.health.go.ug on 3 September 2026: 033B-AP01 OPD New,
# AP02 Total OPD, MA02 Cases Tested with RDT, MA03 RDT Positive Cases,
# MA04 Cases Tested with Microscopy, MA05 Microscopy Positive Cases,
# GP01 No. of samples tested, GP02 No. of samples rejected, GP03 Total MTB
# detected, GP04 Total No. Rif R, GP05 No. of errors/invalid results.
emitted = sorted(set(re.findall(r"SELECT '([A-Z]{2}\d{2})'", ssql)))
check("the emitted indicator codes are exactly those confirmed on the instance",
      emitted, ["AP01", "AP02", "GP01", "GP02", "GP03", "GP04", "GP05",
                "MA02", "MA03", "MA04", "MA05"])
meta = sorted(set(re.findall(r"'(_[a-z_]+)'", ssql)))
check("metadata rows are underscore-prefixed so the compiler skips them",
      all(m.startswith("_") for m in meta) and len(meta) >= 3, True)

print("\nThe corrections that cost three round trips must not regress")
check("new attendance is the first visit in the period, not a category name",
      "ROW_NUMBER() OVER (PARTITION BY PatientNo" in ssql, True)
check("the visit category no longer decides attendance",
      "VisitCategoryID" in ssql, False)
check("results are read from the child table, where the values are",
      ("LabResultsEXT" in ssql, re.search(r"\bdbo\.LabResults\b", ssql) is not None),
      (True, False))
check("only the clause before the first comma is classified",
      "CHARINDEX(','" in ssql, True)
check("negatives are matched before positives",
      ssql.index("NON REACTIVE") < ssql.index("'%REACTIVE%'"), True)
check("the controlled list's misspelling is accepted", "POSTIVE" in ssql, True)
check("tested means resulted, which is what the form asks",
      ssql.count("Verdict IS NOT NULL") >= 3, True)
check("the rejection code is the confirmed one", "'54N'" in ssql, True)

print("\nReports without a script refuse, and say why")
for rt, fragment in [("IPD", "have not been confirmed"),
                     ("HTS", "PreTestingCounseling"),
                     ("MCH", "No compiler yet")]:
    check(f"{rt} refuses with its reason",
          refuses(lambda rt=rt: gen.generate(rt, "202607", "linux", "Monthly", "x"),
                  fragment), True)
check("every non-scriptable report has a stated reason",
      sorted(gen.NOT_SCRIPTABLE) , ["HIV", "HTS", "IPD", "MCH", "PALL", "TBL"])
check("scriptable and non-scriptable together cover every registered report",
      sorted(gen.SCRIPTABLE | set(gen.NOT_SCRIPTABLE)),
      ["HIV", "HTS", "IPD", "MCH", "OPD", "PALL", "SURV", "TBL"])


# ---------------------------------------------------------------------------
# Running the script, added 3 September 2026.
#
# Reported from a real run: `python3 jrrh_extract_opd_202607.py` failed with
#
#     error: the following arguments are required: --user
#
# and nothing else. Correct behaviour from argparse, useless to the person
# holding the file: no example, no hint that "user" means a SQL Server login,
# no mention that the password is prompted for rather than typed on the command
# line. The PowerShell version was fine all along, because a mandatory
# parameter in PowerShell prompts instead of aborting.
#
# These checks actually EXECUTE the generated script, because the fault was in
# its runtime behaviour and no amount of reading the template would have shown
# it.
# ---------------------------------------------------------------------------
import subprocess          # noqa: E402
import sys as _sys         # noqa: E402
import tempfile            # noqa: E402

print("\nThe generated script must be runnable by someone who has not read it")
for rt, per, ptype in (("OPD", "202607", "Monthly"), ("SURV", "2026W35", "Weekly")):
    fname, body = gen.generate(rt, per, "macos", ptype, "105:01")
    tmp = os.path.join(tempfile.mkdtemp(), fname)
    with open(tmp, "w") as fh:
        fh.write(body)

    helped = subprocess.run([_sys.executable, tmp, "--help"],
                            capture_output=True, text=True, timeout=60)
    check(f"{rt}: --help succeeds", helped.returncode, 0)
    check(f"{rt}: --help shows a worked example", "Example:" in helped.stdout, True)
    check(f"{rt}: --help explains what a user is",
          "SQL Server login" in helped.stdout, True)
    check(f"{rt}: --help says a read-only login is preferred",
          "read-only" in helped.stdout, True)
    check(f"{rt}: --help promises the password is not stored",
          "never stored" in helped.stdout, True)

    bare = subprocess.run([_sys.executable, tmp], input="",
                          capture_output=True, text=True, timeout=60)
    check(f"{rt}: running it bare does NOT abort with an argparse usage error",
          "the following arguments are required" in bare.stderr, False)
    check(f"{rt}: running it bare asks for the login instead",
          "SQL Server login for" in bare.stdout, True)
    check(f"{rt}: it names the server it will connect to",
          gen.DEFAULT_SERVER in bare.stdout, True)
    check(f"{rt}: giving no login exits non-zero rather than pretending success",
          bare.returncode, 2)
    check(f"{rt}: and says how to supply one", "--user" in bare.stdout, True)

print("\nThe password must never be a command-line argument")
for os_key in ("macos", "linux"):
    _, body = gen.generate("OPD", "202607", os_key, "Monthly", "105:01")
    check(f"{os_key}: no --password option", '"--password"' in body, False)
    check(f"{os_key}: read through getpass", "getpass.getpass" in body, True)
_, ps = gen.generate("OPD", "202607", "windows", "Monthly", "105:01")
check("windows: password is a secure string", "-AsSecureString" in ps, True)
check("windows: a missing login prompts rather than aborts",
      "Mandatory=$true)][string]$User" in ps, True)
