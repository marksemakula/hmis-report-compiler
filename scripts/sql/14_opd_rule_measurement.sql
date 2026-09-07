/* ==================================================================
   HMIS REPORT COMPILER - WHICH RULE DEFINES AN OPD CLIENT
   ------------------------------------------------------------------
   Server   : 172.20.0.230
   Database : ClinicMasterMOH

   WHY      : ClinicMaster's own "Diagnosis OPD" table returned 371
              sickle cell rows for August 2026. Put through the
              compiler, that same file produces 371 against NC01,
              matching row for row, so neither the ICD-11 mapping nor
              the age and sex banding is responsible for August being
              off. What differs is the extraction query, which decides
              who is an outpatient in a way the front end does not:

                the extract     Visits.VisitStatusID <> '9IP'
                the front end   Diagnosis.VisitType = 'Out Patient'
                the rule given  the client's community is not a ward

              Three definitions of the same word. This script measures
              how far apart they actually are for August, so the extract
              is corrected against evidence rather than assumption, and
              finds the lookup that turns a CommunityID into the name
              the front end prints.

   SAFETY   : Read-only. Catalogue views and COUNT(*) aggregates. No
              name, number, birth date or village is read, and nothing
              is returned that describes a single patient.

   OUTPUT   : ONE grid of roughly 40 rows. Select all, copy, paste back.
   ================================================================== */

SET NOCOUNT ON;

/* ---- 1. What does Visits.CommunityID point at? -------------------
   The community name is on the front end's export but there is no
   table in this database with "community" in its name, so the names
   live in a lookup of a different name. The foreign key says which. */
SELECT   '1_community_fk'                       AS section,
         OBJECT_NAME(fkc.parent_object_id) + '.'
           + COL_NAME(fkc.parent_object_id, fkc.parent_column_id)  AS a,
         'references ' + OBJECT_NAME(fkc.referenced_object_id) + '.'
           + COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS b,
         ''                                     AS c
FROM     ClinicMasterMOH.sys.foreign_key_columns fkc
WHERE    COL_NAME(fkc.parent_object_id, fkc.parent_column_id) LIKE '%communit%'
   OR    COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) LIKE '%communit%'

UNION ALL

/* ---- 2. Fallback if no key is declared ---------------------------
   ClinicMaster does not declare every relationship. A table holding
   both a CommunityID and a name column is the lookup whether or not
   a constraint says so. */
SELECT   '2_lookup_candidates',
         t.name,
         CAST(STUFF((SELECT ', ' + c2.name
                     FROM   ClinicMasterMOH.sys.columns c2
                     WHERE  c2.object_id = t.object_id
                     ORDER BY c2.column_id
                     FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'),
                    1, 2, '') AS nvarchar(4000)),
         CAST(ISNULL((SELECT SUM(pt.rows)
                      FROM   ClinicMasterMOH.sys.partitions pt
                      WHERE  pt.object_id = t.object_id
                        AND  pt.index_id IN (0,1)), 0) AS varchar(20))
FROM     ClinicMasterMOH.sys.tables t
WHERE    EXISTS (SELECT 1 FROM ClinicMasterMOH.sys.columns c
                 WHERE c.object_id = t.object_id AND c.name = 'CommunityID')
  AND    EXISTS (SELECT 1 FROM ClinicMasterMOH.sys.columns c
                 WHERE c.object_id = t.object_id
                   AND (c.name LIKE '%name%' OR c.name LIKE '%descr%'))

UNION ALL

/* ---- 3. The Diagnosis table's columns ----------------------------
   Needed for one further question: whether the extract can fall back
   to the condition's NAME when the code is a local one. Three of
   August's sickle cell rows carry ORTH093 and two carry w3425, which
   are house codes rather than ICD-11 stems. */
SELECT   '3_diagnosis_columns',
         t.name,
         CAST(STUFF((SELECT ', ' + c2.name + ' [' + ty2.name + ']'
                     FROM   ClinicMasterMOH.sys.columns c2
                     JOIN   ClinicMasterMOH.sys.types   ty2
                         ON ty2.user_type_id = c2.user_type_id
                     WHERE  c2.object_id = t.object_id
                     ORDER BY c2.column_id
                     FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'),
                    1, 2, '') AS nvarchar(4000)),
         ''
FROM     ClinicMasterMOH.sys.tables t
WHERE    t.name = 'Diagnosis'

UNION ALL

/* ---- 4. August 2026: how much does VisitStatusID actually remove? -
   The single number that says whether the current rule is the cause
   of the shortfall. */
SELECT   '4_august_totals',
         'OPD diagnoses in August, before any visit-status filter',
         '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Diagnosis d
JOIN     ClinicMasterMOH.dbo.Visits    v ON v.VisitNo = d.TreatmentNo
WHERE    d.ObjectName = 'Visits'
  AND    d.VisitType  = 'Out Patient'
  AND    v.VisitDate >= '2026-08-01'
  AND    v.VisitDate <  '2026-09-01'

UNION ALL

SELECT   '4_august_totals',
         'of those, removed by VisitStatusID = 9IP',
         '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Diagnosis d
JOIN     ClinicMasterMOH.dbo.Visits    v ON v.VisitNo = d.TreatmentNo
WHERE    d.ObjectName = 'Visits'
  AND    d.VisitType  = 'Out Patient'
  AND    v.VisitDate >= '2026-08-01'
  AND    v.VisitDate <  '2026-09-01'
  AND    ISNULL(v.VisitStatusID, '') = '9IP'

UNION ALL

SELECT   '4_august_totals',
         'sickle cell rows (DiseaseCode like 3A51%), no status filter',
         'front end says 371',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Diagnosis d
JOIN     ClinicMasterMOH.dbo.Visits    v ON v.VisitNo = d.TreatmentNo
WHERE    d.ObjectName = 'Visits'
  AND    d.VisitType  = 'Out Patient'
  AND    v.VisitDate >= '2026-08-01'
  AND    v.VisitDate <  '2026-09-01'
  AND    d.DiseaseCode LIKE '3A51%'

UNION ALL

SELECT   '4_august_totals',
         'sickle cell rows surviving VisitStatusID <> 9IP',
         'what the extract sends today',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Diagnosis d
JOIN     ClinicMasterMOH.dbo.Visits    v ON v.VisitNo = d.TreatmentNo
WHERE    d.ObjectName = 'Visits'
  AND    d.VisitType  = 'Out Patient'
  AND    v.VisitDate >= '2026-08-01'
  AND    v.VisitDate <  '2026-09-01'
  AND    d.DiseaseCode LIKE '3A51%'
  AND    ISNULL(v.VisitStatusID, '') <> '9IP'

UNION ALL

/* ---- 5. The visit-status vocabulary on August OPD diagnoses ------ */
SELECT   '5_august_visit_status',
         ISNULL(v.VisitStatusID, '(null)'),
         '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Diagnosis d
JOIN     ClinicMasterMOH.dbo.Visits    v ON v.VisitNo = d.TreatmentNo
WHERE    d.ObjectName = 'Visits'
  AND    d.VisitType  = 'Out Patient'
  AND    v.VisitDate >= '2026-08-01'
  AND    v.VisitDate <  '2026-09-01'
GROUP BY v.VisitStatusID

UNION ALL

/* ---- 6. Communities carrying August OPD diagnoses -----------------
   Identifiers only, and only those with five or more rows, so no
   value here can be tied to a single episode. What matters is the
   count of distinct communities and how concentrated they are; the
   names come from the lookup found in section 1. */
SELECT   '6_august_community',
         ISNULL(v.CommunityID, '(null)'),
         '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Diagnosis d
JOIN     ClinicMasterMOH.dbo.Visits    v ON v.VisitNo = d.TreatmentNo
WHERE    d.ObjectName = 'Visits'
  AND    d.VisitType  = 'Out Patient'
  AND    v.VisitDate >= '2026-08-01'
  AND    v.VisitDate <  '2026-09-01'
GROUP BY v.CommunityID
HAVING   COUNT(*) >= 5

UNION ALL

/* ---- 7. Triage coverage, for the fever count ----------------------
   Triage is polymorphic in the same way Diagnosis is: ObjectName says
   which parent, TreatmentNo is the key into it. This confirms the join
   works and shows how many August visits were triaged at all, which is
   the ceiling on any fever count. */
SELECT   '7_august_triage',
         'OPD visits in August',
         '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits v
WHERE    v.VisitDate >= '2026-08-01'
  AND    v.VisitDate <  '2026-09-01'

UNION ALL

SELECT   '7_august_triage',
         'of those, with a triage record',
         '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits v
WHERE    v.VisitDate >= '2026-08-01'
  AND    v.VisitDate <  '2026-09-01'
  AND    EXISTS (SELECT 1 FROM ClinicMasterMOH.dbo.Triage t
                 WHERE t.TreatmentNo = v.VisitNo
                   AND t.ObjectName  = 'Visits')

UNION ALL

SELECT   '7_august_triage',
         'of those, with a temperature recorded',
         '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits v
WHERE    v.VisitDate >= '2026-08-01'
  AND    v.VisitDate <  '2026-09-01'
  AND    EXISTS (SELECT 1 FROM ClinicMasterMOH.dbo.Triage t
                 WHERE t.TreatmentNo = v.VisitNo
                   AND t.ObjectName  = 'Visits'
                   AND t.Temperature IS NOT NULL
                   AND t.Temperature > 0)

UNION ALL

SELECT   '7_august_triage',
         'of those, 37.5 C or above',
         'candidate EP01a',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits v
WHERE    v.VisitDate >= '2026-08-01'
  AND    v.VisitDate <  '2026-09-01'
  AND    EXISTS (SELECT 1 FROM ClinicMasterMOH.dbo.Triage t
                 WHERE t.TreatmentNo = v.VisitNo
                   AND t.ObjectName  = 'Visits'
                   AND t.Temperature >= 37.5)

UNION ALL

/* ---- 8. The temperature distribution ------------------------------
   A degree-wide histogram. It says whether the readings are in Celsius
   at all, how much of it is 0 or 36.0 typed as a default, and where
   37.5 sits on the curve. Buckets, never a reading. */
SELECT   '8_temperature_histogram',
         CASE WHEN t.Temperature < 30  THEN 'under 30 (suspect)'
              WHEN t.Temperature >= 43 THEN '43 and over (suspect)'
              ELSE CAST(FLOOR(t.Temperature * 2) / 2 AS varchar(10)) END,
         '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Triage t
JOIN     ClinicMasterMOH.dbo.Visits v ON v.VisitNo = t.TreatmentNo
WHERE    t.ObjectName = 'Visits'
  AND    t.Temperature IS NOT NULL
  AND    v.VisitDate >= '2026-08-01'
  AND    v.VisitDate <  '2026-09-01'
GROUP BY CASE WHEN t.Temperature < 30  THEN 'under 30 (suspect)'
              WHEN t.Temperature >= 43 THEN '43 and over (suspect)'
              ELSE CAST(FLOOR(t.Temperature * 2) / 2 AS varchar(10)) END

ORDER BY section, a;
