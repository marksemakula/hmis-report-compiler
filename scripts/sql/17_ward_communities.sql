/* ==================================================================
   HMIS REPORT COMPILER - WHICH COMMUNITIES ARE WARDS   [v4, +A&E]  
   ------------------------------------------------------------------
   Server   : 172.20.0.230
   Database : ClinicMasterMOH

   WHAT SCRIPT 16 FOUND
   --------------------
   The front end does not join to a community table at all. It calls a
   function:

       dbo.GetLookupDataDes(Visits.CommunityID) as Community

   the same one that turns 15F into Female and a branch code into a
   branch name. ClinicMaster keeps every coded list in one place and
   reads it through that function, which is why no table in the
   database has "community" in its name and why the foreign key search
   came back empty.

   So the rule given - an OPD client is one whose community is not a
   ward - can be written exactly as the front end would write it, with
   no guessing at a lookup table:

       dbo.GetLookupDataDes(v.CommunityID) NOT LIKE '%Ward%'

   The first run showed the word is not sufficient. August used 36
   communities; it caught Maternity Ward and GYNAECOLOGY WARD and
   missed three the hospital identifies as in-patient areas: NICU, ICU
   and Accident and Emergency, which is the entry point where admission
   to most wards is done. All three are now named explicitly rather
   than matched by pattern: '%ICU%' would take NICU today and whatever
   opens next year without anyone deciding it should.

   A&E is the one worth watching, because it is much the largest at
   1,147 visits and not everyone who passes through it is admitted.
   Section 5 counts how many of those visits ended in an admission and
   how many did not, which is the difference between excluding an
   in-patient entry point and losing a month of casualty attendances.

   WHAT THIS SCRIPT IS FOR
   -----------------------
   Before that goes into the extract, two things need seeing. Which
   communities the hospital actually uses, by name, and how many visits
   and diagnoses the ward test would remove from August. A rule that
   removes nothing is worth knowing about; so is one that removes more
   than expected.

   The function is called once per distinct community, about thirty
   times, rather than once per row. Scalar functions in SQL Server run
   row by row unless the server can inline them, and fifteen thousand
   calls where thirty will do is the difference between a query that
   returns and one that is killed.

   SAFETY   : Read-only. Community names are organisational - clinics
              and wards, not people - and the counts are aggregates. No
              patient row, name, number or village is read.

   OUTPUT   : ONE grid, roughly 35 rows.
   ================================================================== */

SET NOCOUNT ON;

WITH used AS (
    SELECT   DISTINCT vv.CommunityID
    FROM     ClinicMasterMOH.dbo.Visits vv
    WHERE    vv.VisitDate >= '2026-08-01'
      AND    vv.VisitDate <  '2026-09-01'
),
comm AS (
    SELECT   u.CommunityID,
             ISNULL(ClinicMasterMOH.dbo.GetLookupDataDes(u.CommunityID), '')
                 AS name
    FROM     used u
),
v AS (
    SELECT   vv.VisitNo,
             vv.CommunityID,
             c.name,
             CASE WHEN c.name LIKE '%ward%'
                       OR LTRIM(RTRIM(c.name)) IN
                          ('ACCIDENT AND EMERGENCY', 'ICU', 'NICU')
                  THEN 'ward' ELSE 'not a ward' END
                 AS kind
    FROM     ClinicMasterMOH.dbo.Visits vv
    LEFT JOIN comm c ON c.CommunityID = vv.CommunityID
    WHERE    vv.VisitDate >= '2026-08-01'
      AND    vv.VisitDate <  '2026-09-01'
)
/* ---- 1. Every community August used, named, with its visits -------- */
SELECT   '1_communities'                       AS section,
         v.name                                AS a,
         MAX(v.kind) + ' [' + MAX(ISNULL(v.CommunityID, '(null)')) + ']'
                                               AS b,
         CAST(COUNT(*) AS varchar(20))         AS c
FROM     v
GROUP BY v.name

UNION ALL

/* ---- 1b. And the diagnoses each community carries -----------------
   Section 1 counts visits. NICU shows 71 of those and ICU one, but how
   many DIAGNOSES sit behind them decides what the rule actually takes
   off the 105:01 return, which is the number that matters. */
SELECT   '1b_diagnoses', v.name, '', CAST(COUNT(*) AS varchar(20))
FROM     v
JOIN     ClinicMasterMOH.dbo.Diagnosis d
      ON d.TreatmentNo = v.VisitNo
     AND d.ObjectName  = 'Visits'
     AND d.VisitType   = 'Out Patient'
GROUP BY v.name

UNION ALL

/* ---- 2. What the ward rule would do to August's visits ------------ */
SELECT   '2_visits', v.kind, '', CAST(COUNT(*) AS varchar(20))
FROM     v
GROUP BY v.kind

UNION ALL

/* ---- 3. And to August's outpatient diagnoses ---------------------- */
SELECT   '3_diagnoses', v.kind, '', CAST(COUNT(*) AS varchar(20))
FROM     v
JOIN     ClinicMasterMOH.dbo.Diagnosis d
      ON d.TreatmentNo = v.VisitNo
     AND d.ObjectName  = 'Visits'
     AND d.VisitType   = 'Out Patient'
GROUP BY v.kind

UNION ALL

/* ---- 4. Does the ward rule agree with VisitType? ------------------
   The two rules should be saying the same thing. Where they disagree
   is where a decision has to be made rather than assumed: an
   outpatient diagnosis recorded against a ward community, or an
   inpatient one recorded against a clinic. */
SELECT   '4_agreement',
         v.kind + ' + Diagnosis.VisitType = ' + d.VisitType,
         '',
         CAST(COUNT(*) AS varchar(20))
FROM     v
JOIN     ClinicMasterMOH.dbo.Diagnosis d
      ON d.TreatmentNo = v.VisitNo
     AND d.ObjectName  = 'Visits'
GROUP BY v.kind, d.VisitType

UNION ALL

/* ---- 5. Of the A&E visits, how many became admissions? ------------
   Excluding A&E wholesale is right if it is an in-patient entry point
   and everyone passing through is admitted. Any A&E visit with no
   admission behind it was seen and sent home, which is an outpatient
   attendance, and excluding it removes a real event from the return.
   This says how many of each there are. */
/* The admitted/not test is worked out in a derived table and grouped
   by the resulting column. SQL Server refuses a subquery in a GROUP BY
   list outright - Msg 144 - so the EXISTS cannot appear there, and
   repeating the CASE in both places would be a correctness hazard
   anyway: two copies of one rule drift. */
SELECT   '5_ae_outcome', ae.outcome, '', CAST(COUNT(*) AS varchar(20))
FROM     (SELECT CASE WHEN EXISTS (SELECT 1
                                   FROM   ClinicMasterMOH.dbo.Admissions a
                                   WHERE  a.VisitNo = ae_v.VisitNo)
                      THEN 'A&E visit, admitted'
                      ELSE 'A&E visit, no admission recorded' END AS outcome
          FROM   v AS ae_v
          WHERE  LTRIM(RTRIM(ae_v.name)) = 'ACCIDENT AND EMERGENCY') AS ae
GROUP BY ae.outcome

ORDER BY section, a;
