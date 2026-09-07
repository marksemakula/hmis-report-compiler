/* ==================================================================
   HMIS REPORT COMPILER - RECONCILING AUGUST 2026        [v2, collated]
   ------------------------------------------------------------------
   Server   : 172.20.0.230
   Database : ClinicMasterMOH

   If the first line of your copy does not say v2, it is the earlier
   one and it will fail on a collation conflict at line 53.

   WHERE THIS GOT TO
   -----------------
   Script 14 cleared three suspects and raised a fourth.

     * The visit-status filter removes 105 of 9,144 August OPD
       diagnoses, and exactly one of the 371 sickle cell rows. Wrong
       in principle, but far too small to be the shortfall.
     * The ICD-11 mapping is sound. Even the house codes ORTH093,
       ORTH094 and w3425 reach NC01 correctly.
     * The age banding agrees with ClinicMaster's own Age Category on
       all 371 rows.

   What has never been measured is what the strata query throws away
   before it counts anything. It bands age from the date of birth and
   maps sex through a two-entry table:

       SEX_CODES = 15F Female, 15M Male

   ClinicMaster also issues 15N. A client coded 15N matches neither
   row of that join and is dropped, silently, with every diagnosis
   recorded at the visit. The same happens to any client with no
   usable date of birth, because the query keeps only rows where the
   age resolves. Neither loss is reported anywhere. If August is short
   by a few hundred, this is where they went.

   This script counts those losses, finds the lookup that turns a
   CommunityID into the name the front end prints, and returns August's
   diagnosis codes so the whole 105:01 can be recomputed here and set
   beside what was submitted.

   SAFETY   : Read-only. Catalogue views, COUNT(*) aggregates and the
              disease dictionary. No name, number, birth date or
              village is read. Codes appearing fewer than five times
              are rolled into a single line so no count can be tied to
              one episode.

   OUTPUT   : ONE grid, roughly 300 rows, most of it section 5.
              Export it to CSV rather than pasting if that is easier.
   ================================================================== */

SET NOCOUNT ON;

/* ---- 1. Where the community names live ---------------------------
   No foreign key is declared on CommunityID and no table carries the
   name, so the front end must resolve it inside a view or procedure.
   The text of those objects says how.

   The two COLLATE clauses are not decoration. The catalogue views carry
   Latin1_General_CI_AS_KS_WS while this database is SQL_Latin1_General_CP1_CI_AS,
   and a UNION between them fails outright with "cannot resolve collation
   conflict". Pinning both sides to the database default settles it. */
SELECT   '1_community_objects'                          AS section,
         o.name      COLLATE DATABASE_DEFAULT           AS a,
         o.type_desc COLLATE DATABASE_DEFAULT           AS b,
         ''                                             AS c
FROM     ClinicMasterMOH.sys.sql_modules m
JOIN     ClinicMasterMOH.sys.objects     o ON o.object_id = m.object_id
WHERE    m.definition LIKE '%CommunityID%'

UNION ALL

/* ---- 2. August: what the strata query silently discards -----------
   Three numbers, and the difference between them is the loss. */
SELECT   '2_august_losses', 'OPD visits in August', '', CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits v
WHERE    v.VisitDate >= '2026-08-01' AND v.VisitDate < '2026-09-01'

UNION ALL

SELECT   '2_august_losses', 'of those, sex is neither 15F nor 15M', '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits   v
JOIN     ClinicMasterMOH.dbo.Patients p ON p.PatientNo = v.PatientNo
WHERE    v.VisitDate >= '2026-08-01' AND v.VisitDate < '2026-09-01'
  AND    ISNULL(p.GenderID, '') NOT IN ('15F', '15M')

UNION ALL

SELECT   '2_august_losses', 'of those, no usable date of birth', '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits   v
JOIN     ClinicMasterMOH.dbo.Patients p ON p.PatientNo = v.PatientNo
WHERE    v.VisitDate >= '2026-08-01' AND v.VisitDate < '2026-09-01'
  AND    (p.BirthDate IS NULL OR p.BirthDate < '1900-01-02')

UNION ALL

SELECT   '2_august_losses', 'of those, no patient record at all', '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits v
WHERE    v.VisitDate >= '2026-08-01' AND v.VisitDate < '2026-09-01'
  AND    NOT EXISTS (SELECT 1 FROM ClinicMasterMOH.dbo.Patients p
                     WHERE p.PatientNo = v.PatientNo)

UNION ALL

SELECT   '2_august_losses', 'visits surviving both tests', 'the extract''s denominator',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits   v
JOIN     ClinicMasterMOH.dbo.Patients p ON p.PatientNo = v.PatientNo
WHERE    v.VisitDate >= '2026-08-01' AND v.VisitDate < '2026-09-01'
  AND    ISNULL(p.GenderID, '') IN ('15F', '15M')
  AND    p.BirthDate IS NOT NULL AND p.BirthDate >= '1900-01-02'

UNION ALL

/* ---- 3. And the diagnoses that go with them ---------------------- */
SELECT   '3_august_diagnosis_losses', 'OPD diagnoses in August', '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Diagnosis d
JOIN     ClinicMasterMOH.dbo.Visits    v ON v.VisitNo = d.TreatmentNo
WHERE    d.ObjectName = 'Visits' AND d.VisitType = 'Out Patient'
  AND    v.VisitDate >= '2026-08-01' AND v.VisitDate < '2026-09-01'

UNION ALL

SELECT   '3_august_diagnosis_losses', 'diagnoses lost with unusable sex or age', '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Diagnosis d
JOIN     ClinicMasterMOH.dbo.Visits    v ON v.VisitNo = d.TreatmentNo
LEFT JOIN ClinicMasterMOH.dbo.Patients p ON p.PatientNo = v.PatientNo
WHERE    d.ObjectName = 'Visits' AND d.VisitType = 'Out Patient'
  AND    v.VisitDate >= '2026-08-01' AND v.VisitDate < '2026-09-01'
  AND    (p.PatientNo IS NULL
          OR ISNULL(p.GenderID, '') NOT IN ('15F', '15M')
          OR p.BirthDate IS NULL OR p.BirthDate < '1900-01-02')

UNION ALL

/* ---- 4. The sex vocabulary in use, for August visits -------------- */
SELECT   '4_august_sex',
         ISNULL(p.GenderID, '(no patient record)') COLLATE DATABASE_DEFAULT, '',
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Visits    v
LEFT JOIN ClinicMasterMOH.dbo.Patients p ON p.PatientNo = v.PatientNo
WHERE    v.VisitDate >= '2026-08-01' AND v.VisitDate < '2026-09-01'
GROUP BY p.GenderID

UNION ALL

/* ---- 5. August's OPD diagnoses, by code --------------------------
   The dictionary, not the register: a code, its name and how often it
   was recorded. With this the whole of 105:01 for August can be
   recomputed and set beside what was submitted, line by line. Codes
   used fewer than five times are rolled into one row. */
SELECT   '5_august_codes',
         ISNULL(d.DiseaseCode, '(null)') COLLATE DATABASE_DEFAULT,
         CAST(MAX(ISNULL(d.DiseaseName, '')) AS varchar(200)) COLLATE DATABASE_DEFAULT,
         CAST(COUNT(*) AS varchar(20))
FROM     ClinicMasterMOH.dbo.Diagnosis d
JOIN     ClinicMasterMOH.dbo.Visits    v ON v.VisitNo = d.TreatmentNo
WHERE    d.ObjectName = 'Visits' AND d.VisitType = 'Out Patient'
  AND    v.VisitDate >= '2026-08-01' AND v.VisitDate < '2026-09-01'
GROUP BY d.DiseaseCode
HAVING   COUNT(*) >= 5

UNION ALL

SELECT   '5_august_codes',
         '(all codes used fewer than five times)',
         '',
         CAST(ISNULL(SUM(t.n), 0) AS varchar(20))
FROM     (SELECT COUNT(*) AS n
          FROM   ClinicMasterMOH.dbo.Diagnosis d
          JOIN   ClinicMasterMOH.dbo.Visits    v ON v.VisitNo = d.TreatmentNo
          WHERE  d.ObjectName = 'Visits' AND d.VisitType = 'Out Patient'
            AND  v.VisitDate >= '2026-08-01' AND v.VisitDate < '2026-09-01'
          GROUP BY d.DiseaseCode
          HAVING COUNT(*) < 5) t

ORDER BY section, a;
