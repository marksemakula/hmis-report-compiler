/* ==================================================================
   HMIS REPORT COMPILER — EXTRACTION, STEP A: SCHEMA DISCOVERY
   ------------------------------------------------------------------
   Server   : 172.20.0.230
   Database : ClinicMasterMOH

   PURPOSE  : The 033B weekly extract needs tables the HIVDR work never
              touched - the diagnosis register, the disease dictionary,
              the visit-category lookup, TB screening and TPT. This
              profiles them so the extraction query can be written
              against real column names rather than guesses.

   SAFETY   : Read-only. Catalogue views plus a handful of DISTINCT
              lookups on small reference tables. No patient-level data
              leaves the server.

   OUTPUT   : ONE grid. Paste it back as text.
   ================================================================== */

SET NOCOUNT ON;

/* ---- 1. Columns of the tables the extract will read --------------- */
SELECT   '1_columns'          AS section,
         t.name               AS a,
         CAST(STUFF((SELECT  ', ' + c2.name + ' [' + ty2.name + ']'
                     FROM    ClinicMasterMOH.sys.columns c2
                     JOIN    ClinicMasterMOH.sys.types   ty2
                          ON ty2.user_type_id = c2.user_type_id
                     WHERE   c2.object_id = t.object_id
                     ORDER BY c2.column_id
                     FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '')
              AS nvarchar(4000)) AS b,
         ''                   AS c
FROM     ClinicMasterMOH.sys.tables t
WHERE    t.name IN
         (
             'Diagnosis', 'Diseases', 'ArchivedOPDDiagnosis',
             'VisitCategories', 'VisitsCategories', 'Services',
             'Triage', 'Examinations', 'ClinicalFindings',
             'TBIntensifiedCaseFinding', 'TBEnrollments', 'TPTStart',
             'Items', 'ItemsEXT', 'Inventory', 'ItemsBalanceDetails',
             'Departments', 'Specialities', 'DoctorSpecialties'
         )

UNION ALL

/* ---- 2. Which lookup tables actually exist, and how big ----------- */
SELECT   '2_lookups',
         t.name,
         '',
         CAST(ISNULL((SELECT SUM(p.rows)
                      FROM   ClinicMasterMOH.sys.partitions p
                      WHERE  p.object_id = t.object_id
                        AND  p.index_id IN (0,1)), 0) AS varchar(20))
FROM     ClinicMasterMOH.sys.tables t
WHERE    t.name LIKE '%categor%'
    OR   t.name LIKE '%disease%'
    OR   t.name LIKE '%diagnos%'
    OR   t.name LIKE '%servic%'
    OR   t.name LIKE '%special%'

UNION ALL

/* ---- 3. Visit categories in use, with volume ---------------------- */
SELECT   '3_visitCategory',
         CAST(ISNULL(v.VisitCategoryID, '(null)') AS varchar(100)),
         '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits v
WHERE    v.VisitDate >= DATEADD(month, -6, GETDATE())
GROUP BY v.VisitCategoryID

UNION ALL

/* ---- 4. Visit status values in use -------------------------------- */
SELECT   '4_visitStatus',
         CAST(ISNULL(v.VisitStatusID, '(null)') AS varchar(100)),
         '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits v
WHERE    v.VisitDate >= DATEADD(month, -6, GETDATE())
GROUP BY v.VisitStatusID

UNION ALL

/* ---- 5. Date coverage of the registers the extract will use ------- */
SELECT   '5_coverage', 'Visits.VisitDate',
         CONVERT(varchar(10), MIN(VisitDate), 23) + '  to  ' +
         CONVERT(varchar(10), MAX(VisitDate), 23),
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits

UNION ALL
SELECT   '5_coverage', 'Diagnosis.rows', '', CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Diagnosis

UNION ALL
SELECT   '5_coverage', 'Diseases.rows', '', CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Diseases

ORDER BY section, a;
