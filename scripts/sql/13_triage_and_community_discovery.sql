/* ==================================================================
   HMIS REPORT COMPILER - TRIAGE TEMPERATURE AND CLIENT COMMUNITY
   ------------------------------------------------------------------
   Server   : 172.20.0.230
   Database : ClinicMasterMOH

   PURPOSE  : Two rules have been given for 105:01 and neither can be
              written against the database yet, because the columns
              they need have never been profiled.

                1. A fever is a temperature of 37.5 C or above,
                   recorded at OPD triage. That is the operational
                   definition of EP01a, Suspected Malaria (fever) -
                   until now the only element in the malaria chain
                   with no countable source, which is why reported
                   test positivity has been between 27 and 82 per
                   cent instead of a credible referral-hospital
                   figure.

                2. An OPD client is one whose community is not an
                   in-patient ward, a ward being any community whose
                   name contains the word Ward.

              This script finds where those two live: which table
              holds triage, which column holds temperature, how
              triage joins back to a visit, and where a client's
              community is recorded.

   SAFETY   : Read-only, and catalogue views only. It reads sys.tables
              and sys.columns and nothing else. No patient row is
              touched, so no name, number, birth date, village or
              diagnosis is read anywhere in this script.

   OUTPUT   : ONE grid of roughly 30 to 60 short rows.
              Select all, copy, paste it back.

   NEXT     : With these names confirmed the counting query follows,
              and that one does read patient rows - in aggregate only,
              as the existing extracts do.
   ================================================================== */

SET NOCOUNT ON;

/* ---- 1. Tables that might hold triage or vital signs -------------- */
SELECT   '1_candidate_tables'                       AS section,
         t.name                                     AS a,
         ''                                         AS b,
         CAST(ISNULL((SELECT SUM(pt.rows)
                      FROM   ClinicMasterMOH.sys.partitions pt
                      WHERE  pt.object_id = t.object_id
                        AND  pt.index_id IN (0,1)), 0) AS varchar(20)) AS c
FROM     ClinicMasterMOH.sys.tables t
WHERE    t.name LIKE '%triage%'
   OR    t.name LIKE '%vital%'
   OR    t.name LIKE '%observ%'
   OR    t.name LIKE '%nurs%'
   OR    t.name LIKE '%examin%'
   OR    t.name LIKE '%assess%'

UNION ALL

/* ---- 2. Every column in the database that mentions temperature ----
   Written this way round deliberately. The table may not be called
   Triage at all, and the column may be Temp, Temperature, TempC or
   BodyTemp; searching for the measurement finds it whatever the table
   above is named. Row counts are carried so an empty table is obvious. */
SELECT   '2_temperature_columns',
         t.name + '.' + c.name,
         ty.name + CASE WHEN ty.name LIKE '%char%'
                        THEN '(' + CAST(c.max_length AS varchar(10)) + ')'
                        WHEN ty.name IN ('decimal','numeric')
                        THEN '(' + CAST(c.precision AS varchar(10)) + ','
                                 + CAST(c.scale AS varchar(10)) + ')'
                        ELSE '' END,
         CAST(ISNULL((SELECT SUM(pt.rows)
                      FROM   ClinicMasterMOH.sys.partitions pt
                      WHERE  pt.object_id = t.object_id
                        AND  pt.index_id IN (0,1)), 0) AS varchar(20))
FROM     ClinicMasterMOH.sys.columns c
JOIN     ClinicMasterMOH.sys.tables  t  ON t.object_id     = c.object_id
JOIN     ClinicMasterMOH.sys.types   ty ON ty.user_type_id = c.user_type_id
WHERE    c.name LIKE '%temp%'
  AND    c.name NOT LIKE '%template%'
  AND    c.name NOT LIKE '%tempor%'

UNION ALL

/* ---- 3. Every column that mentions community or ward --------------
   The community may sit on Patients, on Visits, on Admissions or on a
   lookup of its own, and it may be an ID against a name held elsewhere.
   This says which, and the row counts say which is the lookup. */
SELECT   '3_community_columns',
         t.name + '.' + c.name,
         ty.name + CASE WHEN ty.name LIKE '%char%'
                        THEN '(' + CAST(c.max_length AS varchar(10)) + ')'
                        ELSE '' END,
         CAST(ISNULL((SELECT SUM(pt.rows)
                      FROM   ClinicMasterMOH.sys.partitions pt
                      WHERE  pt.object_id = t.object_id
                        AND  pt.index_id IN (0,1)), 0) AS varchar(20))
FROM     ClinicMasterMOH.sys.columns c
JOIN     ClinicMasterMOH.sys.tables  t  ON t.object_id     = c.object_id
JOIN     ClinicMasterMOH.sys.types   ty ON ty.user_type_id = c.user_type_id
WHERE    c.name LIKE '%communit%'
   OR    c.name LIKE '%ward%'

UNION ALL

/* ---- 4. Tables named for community, so the lookup is not missed --- */
SELECT   '4_community_tables',
         t.name,
         '',
         CAST(ISNULL((SELECT SUM(pt.rows)
                      FROM   ClinicMasterMOH.sys.partitions pt
                      WHERE  pt.object_id = t.object_id
                        AND  pt.index_id IN (0,1)), 0) AS varchar(20))
FROM     ClinicMasterMOH.sys.tables t
WHERE    t.name LIKE '%communit%'
   OR    t.name LIKE '%ward%'

UNION ALL

/* ---- 4b. Anywhere a reported fever might be recorded ---------------
   The Ministry's definition of suspected malaria is fever OR history of
   fever. A client who took paracetamol before walking in is suspected
   malaria and will not be 37.5 at triage, so a threshold on the
   thermometer alone undercounts EP01a. If ClinicMaster records the
   complaint as well as the reading, both belong in the count. */
SELECT   '4b_fever_columns',
         t.name + '.' + c.name,
         ty.name,
         CAST(ISNULL((SELECT SUM(pt.rows)
                      FROM   ClinicMasterMOH.sys.partitions pt
                      WHERE  pt.object_id = t.object_id
                        AND  pt.index_id IN (0,1)), 0) AS varchar(20))
FROM     ClinicMasterMOH.sys.columns c
JOIN     ClinicMasterMOH.sys.tables  t  ON t.object_id     = c.object_id
JOIN     ClinicMasterMOH.sys.types   ty ON ty.user_type_id = c.user_type_id
WHERE    c.name LIKE '%fever%'
   OR    c.name LIKE '%complaint%'
   OR    c.name LIKE '%presenting%'

UNION ALL

/* ---- 5. Full columns of the candidate tables ----------------------
   Needed for the join back to a visit. ClinicMaster is polymorphic in
   places - Diagnosis uses ObjectName plus TreatmentNo rather than a
   VisitNo - so the key cannot be assumed and has to be read. */
SELECT   '5_columns',
         t.name,
         CAST(STUFF((SELECT  ', ' + c2.name + ' [' + ty2.name + ']'
                     FROM    ClinicMasterMOH.sys.columns c2
                     JOIN    ClinicMasterMOH.sys.types   ty2
                          ON ty2.user_type_id = c2.user_type_id
                     WHERE   c2.object_id = t.object_id
                     ORDER BY c2.column_id
                     FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'),
                    1, 2, '') AS nvarchar(4000)),
         CAST(ISNULL((SELECT SUM(pt.rows)
                      FROM   ClinicMasterMOH.sys.partitions pt
                      WHERE  pt.object_id = t.object_id
                        AND  pt.index_id IN (0,1)), 0) AS varchar(20))
FROM     ClinicMasterMOH.sys.tables t
WHERE    t.name LIKE '%triage%'
   OR    t.name LIKE '%vital%'
   OR    t.name LIKE '%communit%'
   OR    t.name IN ('Visits', 'Patients', 'Admissions')

ORDER BY section, a;
