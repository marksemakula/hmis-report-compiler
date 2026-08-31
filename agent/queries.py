"""Versioned, reviewed queries against ClinicMaster.

These live with the agent, not on the server. A job from the compiler says only
"105:01 for June 2026" — it never carries SQL. That way a compromised or
spoofed server cannot make an agent sitting inside the hospital run arbitrary
statements against a database of HIV and TB records.

Every statement here must be read-only. The agent opens its connection with a
read-only login and refuses to run anything matching WRITE_GUARD.
"""
import re

# Any of these in a statement means it is not a read. The agent checks before
# executing, so a careless edit here fails loudly rather than altering records.
WRITE_GUARD = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|MERGE|EXEC|EXECUTE|GRANT|REVOKE)\b",
    re.I)

DATABASE = "ClinicMasterMOH"

# ---------------------------------------------------------------------------
# SCHEMA PROBE
# ---------------------------------------------------------------------------
# The diagnosis register's column names were never confirmed. Run
#     python jrrh_agent.py --schema
# and the agent prints what follows, so DIAGNOSIS_SOURCE below can be completed
# without anyone opening Azure Data Studio.
SCHEMA_PROBE = f"""
SELECT t.name AS table_name,
       STUFF((SELECT ', ' + c2.name + ' [' + ty2.name + ']'
              FROM {DATABASE}.sys.columns c2
              JOIN {DATABASE}.sys.types   ty2 ON ty2.user_type_id = c2.user_type_id
              WHERE c2.object_id = t.object_id
              ORDER BY c2.column_id
              FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '') AS columns
FROM {DATABASE}.sys.tables t
WHERE t.name IN ('Diagnosis', 'Diseases', 'ArchivedOPDDiagnosis', 'Visits', 'Patients')
ORDER BY t.name;
"""

# ---------------------------------------------------------------------------
# DIAGNOSIS SOURCE — the one part still to confirm
# ---------------------------------------------------------------------------
# Set CONFIRMED to True once the names below match what --schema reports. Until
# then the agent extracts attendance only and says so, rather than guessing at
# column names and silently producing a report with no conditions in it.
DIAGNOSIS_SOURCE = {
    "confirmed": False,
    "table": "Diagnosis",
    "visit_col": "VisitNo",        # link to Visits.VisitNo
    "disease_col": "DiseasesID",   # link to Diseases
    "disease_table": "Diseases",
    "disease_id_col": "DiseasesID",
    "disease_name_col": "DiseaseName",
}

# ---------------------------------------------------------------------------
# 105:01 OPD — attendance strata
# ---------------------------------------------------------------------------
# Counts by age in whole years, sex and visit category. The agent turns age into
# the HMIS band; doing it here in SQL would duplicate the banding rules in two
# languages and invite them to drift.
#
# Age is taken at the visit date, not today: a report for June must band a child
# by how old they were in June.
OPD_ATTENDANCE = f"""
SELECT  CASE WHEN p.BirthDate IS NULL OR p.BirthDate < '1900-01-02' THEN NULL
             ELSE DATEDIFF(day, p.BirthDate, v.VisitDate) / 365.25 END AS age_years,
        p.GenderID                                     AS sex,
        ISNULL(v.VisitCategoryID, '')                  AS visit_category,
        COUNT(*)                                       AS n
FROM    {DATABASE}.dbo.Visits   v
JOIN    {DATABASE}.dbo.Patients p ON p.PatientNo = v.PatientNo
WHERE   v.VisitDate >= ? AND v.VisitDate < ?
GROUP BY CASE WHEN p.BirthDate IS NULL OR p.BirthDate < '1900-01-02' THEN NULL
              ELSE DATEDIFF(day, p.BirthDate, v.VisitDate) / 365.25 END,
         p.GenderID,
         ISNULL(v.VisitCategoryID, '');
"""


def opd_diagnosis_sql() -> str:
    """Built from DIAGNOSIS_SOURCE so completing it is a one-place edit."""
    d = DIAGNOSIS_SOURCE
    return f"""
SELECT  CASE WHEN p.BirthDate IS NULL OR p.BirthDate < '1900-01-02' THEN NULL
             ELSE DATEDIFF(day, p.BirthDate, v.VisitDate) / 365.25 END AS age_years,
        p.GenderID                                     AS sex,
        ISNULL(v.VisitCategoryID, '')                  AS visit_category,
        ds.{d['disease_name_col']}                     AS diagnosis,
        COUNT(*)                                       AS n
FROM    {DATABASE}.dbo.{d['table']}   dg
JOIN    {DATABASE}.dbo.Visits   v  ON v.VisitNo   = dg.{d['visit_col']}
JOIN    {DATABASE}.dbo.Patients p  ON p.PatientNo = v.PatientNo
JOIN    {DATABASE}.dbo.{d['disease_table']} ds
     ON ds.{d['disease_id_col']} = dg.{d['disease_col']}
WHERE   v.VisitDate >= ? AND v.VisitDate < ?
GROUP BY CASE WHEN p.BirthDate IS NULL OR p.BirthDate < '1900-01-02' THEN NULL
              ELSE DATEDIFF(day, p.BirthDate, v.VisitDate) / 365.25 END,
         p.GenderID,
         ISNULL(v.VisitCategoryID, ''),
         ds.{d['disease_name_col']};
"""


def check_read_only(sql: str, label: str = "query"):
    hit = WRITE_GUARD.search(sql or "")
    if hit:
        raise RuntimeError(
            f"Refusing to run {label}: it contains '{hit.group(0)}'. "
            "The agent runs read-only statements only.")
    return sql
