"""Generated extraction scripts for a machine on the hospital LAN.

The compiler cannot reach ClinicMaster at 172.20.0.230 from Vercel. Rather than
run a permanent agent, this route hands the user a script tailored to their
operating system, their report and their period. They take it to a machine on
the hospital network, run it once, and upload the file it writes.

Two properties are worth stating, because they are why the script is generated
here rather than written by hand:

  * The period is baked in. A script downloaded for June 2026 cannot be run
    against May by accident — the dates are literals in the SQL, derived from a
    period the server has already validated.
  * The output is aggregated. The script writes counts by diagnosis, age band,
    sex and visit type. No patient row is written to disk, so nothing
    identifying can be uploaded, emailed or left in a Downloads folder.

Windows gets PowerShell, which queries SQL Server through .NET with nothing
installed — the decisive advantage on a locked-down hospital machine. macOS and
Linux get Python, which those platforms almost always have.
"""
import re
from datetime import date

from .periods import bounds, describe

# Age bands, in the order the script must test them. Kept here so the generated
# scripts, the agent and api/_lib/compiler.py all express one rule; the drift
# between them is what scripts/test_scripts.py exists to catch.
BAND_RULES = [
    (28 / 365.0, "0-28Dys"),
    (5.0, "29Dys-4Yrs"),
    (10.0, "5-9Yrs"),
    (20.0, "10-19Yrs"),
    (999.0, "20+Yrs"),
]

# ClinicMaster codes sex as 15F / 15M / 15N, not Male / Female. An earlier
# version of these scripts matched on the words and would have discarded every
# visit as "no recognised sex", writing an empty file. Confirmed 25 Aug 2026:
# 15F 143,326 · 15M 82,267 · 15N 31.
SEX_CODES = {"15F": "Female", "15M": "Male"}

# The row that carries visit counts rather than a condition.
ATTENDANCE_SENTINEL = "(attendance)"

DATABASE = "ClinicMasterMOH"
DEFAULT_SERVER = "172.20.0.230"

OS_CHOICES = {
    "windows": {"label": "Microsoft Windows", "ext": "ps1", "runtime": "PowerShell"},
    "macos":   {"label": "macOS",             "ext": "py",  "runtime": "Python 3"},
    "linux":   {"label": "Linux",             "ext": "py",  "runtime": "Python 3"},
}

# Reports a script can be generated for. Others are upload-only for now.
SCRIPTABLE = {"OPD"}

# Diagnostic scripts, which describe the database rather than extract a report.
# They take no period and return reference data only, never patient rows.
UTILITIES = {
    "profile": {
        "label": "Database profile",
        "note": "Table columns, row counts, lookup values and date coverage. "
                "Reference data only — no patient row is read.",
        "output": "JRRH_clinicmaster_profile.csv",
    },
    "diseases": {
        "label": "Disease dictionary",
        "note": "The complete Diseases table, needed to map ClinicMaster "
                "conditions onto HMIS 105 elements and to check whether ICD-11 "
                "codes are populated.",
        "output": "JRRH_clinicmaster_diseases.csv",
    },
}


def opd_sql(start: date, end_exclusive: date) -> str:
    """Read-only aggregate for HMIS 105:01, one period.

    Confirmed against the live schema on 25 August 2026:

      * Diagnosis has no VisitNo. It uses ClinicMaster's polymorphic pattern —
        ObjectName names the parent entity ('Visits', 'Admissions', 'IPDDoctor',
        'Deaths') and TreatmentNo is the key into it. OPD diagnoses are those
        with ObjectName = 'Visits'.
      * Diagnosis.VisitType carries exactly two values, 'Out Patient' and
        'In Patient'. That is the OPD/IPD discriminator the front end shows as
        two separate tables.
      * GenderID is coded '15F' / '15M' / '15N', NOT 'Male' / 'Female'.
      * Diseases.DiseaseCode is a genuine ICD-11 stem for 16,917 of 18,036
        entries. Join on the CODE, never the name: Diagnosis holds 7,452
        distinct names against only 5,679 distinct codes, so the names have
        drifted and would split a single condition across several rows.

    Two grains come back in one result, distinguished by the diagnosis column:

      * rows where diagnosis = '(attendance)' count VISITS — one per visit,
        for OA01/OA02
      * every other row counts DIAGNOSES — a visit with three conditions
        recorded contributes three, which is what the Ministry asks for

    New versus re-attendance follows the Ministry rule: a client's first visit
    in the period is new, later visits are re-attendances."""
    return f"""WITH v AS (
    SELECT  vv.VisitNo,
            vv.PatientNo,
            vv.VisitDate,
            ROW_NUMBER() OVER (PARTITION BY vv.PatientNo ORDER BY vv.VisitDate, vv.VisitNo)
                AS seq_in_period
    FROM    {DATABASE}.dbo.Visits vv
    WHERE   vv.VisitDate >= '{start.isoformat()}'
      AND   vv.VisitDate <  '{end_exclusive.isoformat()}'
      AND   ISNULL(vv.VisitStatusID, '') <> '9IP'   -- exclude inpatient episodes
), b AS (
    SELECT  v.VisitNo,
            CASE WHEN p.BirthDate IS NULL OR p.BirthDate < '1900-01-02' THEN NULL
                 ELSE DATEDIFF(day, p.BirthDate, v.VisitDate) / 365.25 END AS age_years,
            p.GenderID                                             AS sex,
            CASE WHEN v.seq_in_period = 1 THEN 'New' ELSE 'Re' END  AS visit_category
    FROM    v
    JOIN    {DATABASE}.dbo.Patients p ON p.PatientNo = v.PatientNo
)
SELECT  b.age_years, b.sex, b.visit_category,
        '(attendance)'  AS diagnosis,
        COUNT(*)        AS n
FROM    b
GROUP BY b.age_years, b.sex, b.visit_category

UNION ALL

SELECT  b.age_years, b.sex, b.visit_category,
        d.DiseaseCode   AS diagnosis,
        COUNT(*)        AS n
FROM    b
JOIN    {DATABASE}.dbo.Diagnosis d
     ON d.TreatmentNo = b.VisitNo
    AND d.ObjectName  = 'Visits'
    AND d.VisitType   = 'Out Patient'
WHERE   d.DiseaseCode IS NOT NULL
GROUP BY b.age_years, b.sex, b.visit_category, d.DiseaseCode"""


def profile_sql() -> str:
    """One read-only query describing the database's shape.

    Catalogue views and small lookup distributions only — no patient row is
    returned, and nothing here reads a name, number or date of birth. Its
    purpose is to let the report queries be written against real column names
    instead of guesses."""
    tables = ("'Visits','Patients','Diagnosis','Diseases','ArchivedOPDDiagnosis',"
              "'ArchiveIPDDiagnosis','Items','ItemsEXT','ItemsIncome','LabRequests',"
              "'LabRequestDetails','LabResults','LabTests','PatientsART','ARTRegimen',"
              "'TBIntensifiedCaseFinding','TPTStart','BranchDetails','HealthUnits'")
    return f"""SELECT '1_columns' AS section, t.name AS a,
       CAST(STUFF((SELECT ', ' + c.name + ' [' + ty.name + ']'
                   FROM {DATABASE}.sys.columns c
                   JOIN {DATABASE}.sys.types ty ON ty.user_type_id = c.user_type_id
                   WHERE c.object_id = t.object_id
                   ORDER BY c.column_id
                   FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '')
            AS nvarchar(4000)) AS b,
       CAST(ISNULL((SELECT SUM(pt.rows) FROM {DATABASE}.sys.partitions pt
                    WHERE pt.object_id = t.object_id AND pt.index_id IN (0,1)), 0)
            AS varchar(20)) AS c
FROM {DATABASE}.sys.tables t
WHERE t.name IN ({tables})

UNION ALL
SELECT '2_diagnosis_tables', t.name, '',
       CAST(ISNULL((SELECT SUM(pt.rows) FROM {DATABASE}.sys.partitions pt
                    WHERE pt.object_id = t.object_id AND pt.index_id IN (0,1)), 0)
            AS varchar(20))
FROM {DATABASE}.sys.tables t
WHERE t.name LIKE '%diagnos%' OR t.name LIKE '%disease%'

UNION ALL
SELECT '3_gender', CAST(ISNULL(GenderID,'(null)') AS varchar(60)), '',
       CAST(COUNT(*) AS varchar(20))
FROM {DATABASE}.dbo.Patients GROUP BY GenderID

UNION ALL
SELECT '4_visit_category', CAST(ISNULL(VisitCategoryID,'(null)') AS varchar(60)), '',
       CAST(COUNT(*) AS varchar(20))
FROM {DATABASE}.dbo.Visits
WHERE VisitDate >= DATEADD(month,-6,GETDATE())
GROUP BY VisitCategoryID

UNION ALL
SELECT '5_visit_status', CAST(ISNULL(VisitStatusID,'(null)') AS varchar(60)), '',
       CAST(COUNT(*) AS varchar(20))
FROM {DATABASE}.dbo.Visits
WHERE VisitDate >= DATEADD(month,-6,GETDATE())
GROUP BY VisitStatusID

UNION ALL
SELECT '6_coverage', 'Visits.VisitDate',
       CONVERT(varchar(10),MIN(VisitDate),23) + ' to ' + CONVERT(varchar(10),MAX(VisitDate),23),
       CAST(COUNT(*) AS varchar(20))
FROM {DATABASE}.dbo.Visits

UNION ALL
SELECT '7_diagnoses_per_visit', 'diagnoses per visit, last 3 months', '',
       CAST(COUNT(*) AS varchar(20))
FROM {DATABASE}.dbo.Diagnosis d
WHERE EXISTS (SELECT 1 FROM {DATABASE}.dbo.Visits v2
              WHERE v2.VisitNo = d.VisitNo
                AND v2.VisitDate >= DATEADD(month,-3,GETDATE()))

UNION ALL
SELECT '7_diagnoses_per_visit', 'visits, last 3 months', '',
       CAST(COUNT(*) AS varchar(20))
FROM {DATABASE}.dbo.Visits
WHERE VisitDate >= DATEADD(month,-3,GETDATE())

ORDER BY section, a"""


def diseases_sql() -> str:
    """The complete disease dictionary. Reference data, not patient data —
    it is the key to mapping ClinicMaster conditions onto HMIS 105 elements,
    and to seeing whether ICD-11 codes are actually populated."""
    return f"SELECT * FROM {DATABASE}.dbo.Diseases"


def output_name(report_type: str, period: str) -> str:
    return f"JRRH_{report_type}_{period}_strata.csv"


def script_name(report_type: str, period: str, os_key: str) -> str:
    return f"jrrh_extract_{report_type.lower()}_{period}.{OS_CHOICES[os_key]['ext']}"


# ---------------------------------------------------------------- PowerShell
POWERSHELL = r'''<#
    JRRH HMIS extraction — {report_label}
    Period: {period_label}   ({period})
    Generated: {generated}

    Run this on a machine connected to the hospital network. It queries
    ClinicMaster read-only, aggregates here, and writes:

        {output}

    Upload that file on the Compile page. It contains counts only — no patient
    names, numbers or dates of birth are written to disk.

    Requires nothing installed: PowerShell queries SQL Server through .NET.

        .\{script} -User readonly_user

#>
param(
    [string]$Server   = "{server}",
    [string]$Database = "{database}",
    [Parameter(Mandatory=$true)][string]$User,
    [string]$OutFile  = "{output}"
)

$ErrorActionPreference = "Stop"
$Password = Read-Host -Prompt "Password for SQL login '$User'" -AsSecureString
$Plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password))

$Sql = @'
{sql}
'@

function Get-Band([double]$Years) {{
{band_ps}
    return "20+Yrs"
}}

Write-Host "Connecting to $Server ..."
$conn = New-Object System.Data.SqlClient.SqlConnection
$conn.ConnectionString = "Server=$Server;Database=$Database;User ID=$User;Password=$Plain;TrustServerCertificate=True;Connect Timeout=20"
$conn.Open()
$cmd = $conn.CreateCommand()
$cmd.CommandText = $Sql
$cmd.CommandTimeout = 600
$reader = $cmd.ExecuteReader()

$tally = @{{}}
$skippedAge = 0
$skippedSex = 0

# ClinicMaster codes sex as 15F / 15M / 15N. Matching on the words "Male" and
# "Female" would discard every row.
$SexCodes = @{{ {sex_ps} }}

while ($reader.Read()) {{
    $n = [int]$reader["n"]
    if ($n -le 0) {{ continue }}
    if ($reader["age_years"] -eq [DBNull]::Value) {{ $skippedAge += $n; continue }}

    $sex = $SexCodes[([string]$reader["sex"]).Trim()]
    if (-not $sex) {{ $skippedSex += $n; continue }}

    $band  = Get-Band ([double]$reader["age_years"])
    # New / Re already decided in SQL by first visit in the period.
    $visit = ([string]$reader["visit_category"]).Trim()
    $diag  = ([string]$reader["diagnosis"]).Trim()
    if (-not $diag) {{ $diag = "(no diagnosis code)" }}

    $key = "$diag|$band|$sex|$visit"
    if ($tally.ContainsKey($key)) {{ $tally[$key] += $n }} else {{ $tally[$key] = $n }}
}}
$reader.Close(); $conn.Close()

$rows = foreach ($k in ($tally.Keys | Sort-Object)) {{
    $p = $k -split '\|'
    [PSCustomObject]@{{
        diagnosis = $p[0]
        band      = $p[1]
        sex       = $p[2]
        visit     = $p[3]
        n         = $tally[$k]
    }}
}}

$rows | Export-Csv -Path $OutFile -NoTypeInformation -Encoding UTF8

$total = ($rows | Measure-Object -Property n -Sum).Sum
Write-Host ""
Write-Host "Wrote $OutFile"
Write-Host "  $($rows.Count) strata, $total visits"
if ($skippedAge -gt 0) {{ Write-Warning "$skippedAge visits had no usable date of birth and were not banded." }}
if ($skippedSex -gt 0) {{ Write-Warning "$skippedSex visits had no recognised sex." }}
Write-Host ""
Write-Host "Upload this file on the Compile page for {report_label}, {period_label}."
'''

# ---------------------------------------------------------------- Python
PYTHON = r'''#!/usr/bin/env python3
"""JRRH HMIS extraction — {report_label}
Period: {period_label}   ({period})
Generated: {generated}

Run this on a machine connected to the hospital network. It queries ClinicMaster
read-only, aggregates here, and writes:

    {output}

Upload that file on the Compile page. It contains counts only — no patient
names, numbers or dates of birth are written to disk.

    pip install pymssql
    python {script} --user readonly_user
"""
import argparse
import csv
import getpass
import sys

SERVER = "{server}"
DATABASE = "{database}"
OUTPUT = "{output}"

SQL = """{sql}"""

BANDS = [
{band_py}
]
SEX_CODES = {{{sex_py}}}


def band(years):
    for limit, label in BANDS:
        if years < limit or (label == "0-28Dys" and years <= limit):
            return label
    return "20+Yrs"


def connect(server, database, user, password):
    try:
        import pymssql
        return pymssql.connect(server=server, user=user, password=password,
                               database=database, login_timeout=20, timeout=600)
    except ImportError:
        pass
    try:
        import pyodbc
        for drv in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"):
            try:
                return pyodbc.connect(
                    f"DRIVER={{{{{{drv}}}}}};SERVER={{server}};DATABASE={{database}};"
                    f"UID={{user}};PWD={{password}};TrustServerCertificate=yes",
                    timeout=20)
            except Exception:
                continue
    except ImportError:
        pass
    sys.exit("No SQL Server driver found. Install one:  pip install pymssql")


def main():
    ap = argparse.ArgumentParser(description="JRRH {report_label} extraction for {period}")
    ap.add_argument("--server", default=SERVER)
    ap.add_argument("--database", default=DATABASE)
    ap.add_argument("--user", required=True)
    ap.add_argument("--out", default=OUTPUT)
    args = ap.parse_args()

    password = getpass.getpass(f"Password for SQL login {{args.user!r}}: ")
    print(f"Connecting to {{args.server}} ...")
    conn = connect(args.server, args.database, args.user, password)
    cur = conn.cursor()
    cur.execute(SQL)

    tally, skipped_age, skipped_sex = {{}}, 0, 0
    for age_years, sex_code, visit, diagnosis, n in cur.fetchall():
        n = int(n or 0)
        if n <= 0:
            continue
        if age_years is None:
            skipped_age += n
            continue
        sex = SEX_CODES.get(str(sex_code or "").strip())
        if not sex:
            skipped_sex += n
            continue
        # New / Re already decided in SQL by first visit in the period.
        key = (str(diagnosis or "(no diagnosis code)").strip(),
               band(float(age_years)), sex, str(visit or "New").strip())
        tally[key] = tally.get(key, 0) + n

    cur.close()
    conn.close()

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["diagnosis", "band", "sex", "visit", "n"])
        for (d, b, s, v), n in sorted(tally.items()):
            w.writerow([d, b, s, v, n])

    total = sum(tally.values())
    print(f"\nWrote {{args.out}}")
    print(f"  {{len(tally)}} strata, {{total:,}} visits")
    if skipped_age:
        print(f"  warning: {{skipped_age:,}} visits had no usable date of birth "
              "and were not banded.")
    if skipped_sex:
        print(f"  warning: {{skipped_sex:,}} visits had no recognised sex.")
    print("\nUpload this file on the Compile page for {report_label}, {period_label}.")


if __name__ == "__main__":
    main()
'''



# ---------------------------------------------------------------- generic
# Utility scripts run one read-only query and write every row to CSV. They need
# no banding or mapping, so a single template serves both platforms' logic and
# only the surrounding syntax differs.
GENERIC_PS = r'''<#
    JRRH ClinicMaster — {label}
    Generated: {generated}

    {note}

    Run on a machine connected to the hospital network, then send the file it
    writes back. Read-only throughout.

        .\{script} -User readonly_user
#>
param(
    [string]$Server   = "{server}",
    [string]$Database = "{database}",
    [Parameter(Mandatory=$true)][string]$User,
    [string]$OutFile  = "{output}"
)
$ErrorActionPreference = "Stop"
$Password = Read-Host -Prompt "Password for SQL login '$User'" -AsSecureString
$Plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password))

$Sql = @'
{sql}
'@

Write-Host "Connecting to $Server ..."
$conn = New-Object System.Data.SqlClient.SqlConnection
$conn.ConnectionString = "Server=$Server;Database=$Database;User ID=$User;Password=$Plain;TrustServerCertificate=True;Connect Timeout=20"
$conn.Open()
$adapter = New-Object System.Data.SqlClient.SqlDataAdapter($Sql, $conn)
$table = New-Object System.Data.DataTable
$adapter.SelectCommand.CommandTimeout = 600
[void]$adapter.Fill($table)
$conn.Close()

$table | Export-Csv -Path $OutFile -NoTypeInformation -Encoding UTF8
Write-Host ""
Write-Host "Wrote $OutFile  ($($table.Rows.Count) rows)"
Write-Host "Send this file back so the report queries can be written against real columns."
'''

GENERIC_PY = r'''#!/usr/bin/env python3
"""JRRH ClinicMaster — {label}
Generated: {generated}

{note}

Run on a machine connected to the hospital network, then send the file it
writes back. Read-only throughout.

    pip install pymssql
    python {script} --user readonly_user
"""
import argparse
import csv
import getpass
import sys

SERVER = "{server}"
DATABASE = "{database}"
OUTPUT = "{output}"

SQL = """{sql}"""


def connect(server, database, user, password):
    try:
        import pymssql
        return pymssql.connect(server=server, user=user, password=password,
                               database=database, login_timeout=20, timeout=600)
    except ImportError:
        pass
    try:
        import pyodbc
        for drv in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"):
            try:
                return pyodbc.connect(
                    f"DRIVER={{{{{{drv}}}}}};SERVER={{server}};DATABASE={{database}};"
                    f"UID={{user}};PWD={{password}};TrustServerCertificate=yes",
                    timeout=20)
            except Exception:
                continue
    except ImportError:
        pass
    sys.exit("No SQL Server driver found. Install one:  pip install pymssql")


def main():
    ap = argparse.ArgumentParser(description="JRRH {label}")
    ap.add_argument("--server", default=SERVER)
    ap.add_argument("--database", default=DATABASE)
    ap.add_argument("--user", required=True)
    ap.add_argument("--out", default=OUTPUT)
    args = ap.parse_args()

    password = getpass.getpass(f"Password for SQL login {{args.user!r}}: ")
    print(f"Connecting to {{args.server}} ...")
    conn = connect(args.server, args.database, args.user, password)
    cur = conn.cursor()
    cur.execute(SQL)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    cur.close()
    conn.close()

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])

    print(f"\nWrote {{args.out}}  ({{len(rows):,}} rows)")
    print("Send this file back so the report queries can be written against real columns.")


if __name__ == "__main__":
    main()
'''

def generate(report_type: str, period: str, os_key: str, period_type: str,
             report_label: str, server: str = DEFAULT_SERVER) -> tuple:
    """Return (filename, text) for the requested script."""
    report_type = (report_type or "").upper()
    os_key = (os_key or "").lower()
    if os_key not in OS_CHOICES:
        raise ValueError(f"Unknown operating system {os_key!r}; "
                         f"expected one of {sorted(OS_CHOICES)}")
    kind = (report_type or "").lower()
    if kind in UTILITIES:
        u = UTILITIES[kind]
        name = f"jrrh_{kind}.{OS_CHOICES[os_key]['ext']}"
        common = {
            "label": u["label"], "note": u["note"], "generated": date.today().isoformat(),
            "server": server, "database": DATABASE, "output": u["output"],
            "script": name,
            "sql": profile_sql() if kind == "profile" else diseases_sql(),
        }
        tpl = GENERIC_PS if os_key == "windows" else GENERIC_PY
        return name, tpl.format(**common)

    if report_type not in SCRIPTABLE:
        raise ValueError(
            f"No extraction script exists for {report_type} yet. "
            f"Available: {', '.join(sorted(SCRIPTABLE | set(UTILITIES)))}")

    span = bounds(period_type, period)
    if not span:
        raise ValueError(f"{period!r} is not a valid {period_type.lower()} period")
    start, end = span
    end_exclusive = date.fromordinal(end.toordinal() + 1)

    sql = opd_sql(start, end_exclusive)
    common = {
        "report_label": report_label,
        "period": period,
        "period_label": describe(period_type, period),
        "generated": date.today().isoformat(),
        "server": server,
        "database": DATABASE,
        "output": output_name(report_type, period),
        "script": script_name(report_type, period, os_key),
        "sql": sql,
    }

    if os_key == "windows":
        band_ps = "\n".join(
            f'    if ($Years -lt {limit!r}{" -or $Years -le " + repr(limit) if label == "0-28Dys" else ""}) '
            f'{{ return "{label}" }}'
            for limit, label in BAND_RULES[:-1])
        text = POWERSHELL.format(
            band_ps=band_ps,
            sex_ps="; ".join(f'"{k}" = "{v}"' for k, v in SEX_CODES.items()),
            **common)
    else:
        band_py = "\n".join(f"    ({limit!r}, {label!r})," for limit, label in BAND_RULES)
        text = PYTHON.format(
            band_py=band_py,
            sex_py=", ".join(f"{k!r}: {v!r}" for k, v in SEX_CODES.items()),
            **common)

    return common["script"], text


def strata_columns():
    return ["diagnosis", "band", "sex", "visit", "n"]


def looks_like_strata(fieldnames) -> bool:
    """Whether an uploaded file is a strata CSV from a generated script rather
    than a line-listed register extract."""
    if not fieldnames:
        return False
    got = {re.sub(r"\s+", "", str(f or "")).lower() for f in fieldnames if f}
    return set(strata_columns()).issubset(got)
