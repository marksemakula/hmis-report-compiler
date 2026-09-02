/* ==================================================================
   LAB RESULTS - WHAT IS ALREADY ON SITE
   ------------------------------------------------------------------
   Server   : 172.20.0.230        Database: ClinicMasterMOH

   WHY THIS EXISTS
   Script 10 settled the question we thought we were asking. ALIS speaks
   HL7 FHIR: ClinicMaster posts a Bundle of type "transaction" and gets
   back a Bundle of type "transaction-response". It has done so 104,137
   times, and 28,211 results have already come back and been stored -
   locally, in INTLabResults, with 250,667 analyte-level rows beside them
   in INTLabResultsEXT.

   So for REPORTING purposes there is nothing to fetch across the network.
   The lab data the HMIS forms need is already in the same database as the
   visits. What we do not yet know is:

     a) which tests exist and in what volume, so the 105:04-05 and lab
        sections can be mapped to real test codes rather than guesses;
     b) what a result actually looks like - "Positive", "POS", "1", "R" -
        because a tally of positives cannot be written against a
        vocabulary we have not seen;
     c) how a specimen joins back to a visit, without which no lab figure
        can be disaggregated by age and sex, and every lab cell in the
        form stays blank.

   SAFETY
   Section 5 lists distinct RESULT VALUES. A result value on its own names
   nobody, but a value that occurs once could in principle be matched to a
   person by someone who already knew the case. It is therefore filtered to
   values occurring five times or more. Nothing here returns a specimen
   number, a patient number, a name or a date of birth.

   Section 7 returns the COLUMN NAMES of INTAgents and nothing else. That
   table configures the integration and may hold an endpoint credential.
   Do not select from it.

   USAGE : Run the whole script. It returns ONE grid.
   ================================================================== */

SET NOCOUNT ON;

IF OBJECT_ID('tempdb..#lab') IS NOT NULL DROP TABLE #lab;
CREATE TABLE #lab (seq int IDENTITY(1,1), section varchar(40), item varchar(400),
                   detail varchar(400), number varchar(40));

/* ---- 1. Every table that could hold laboratory data --------------- */
INSERT INTO #lab (section, item, detail, number)
SELECT '1_lab_tables', t.name, '',
       CAST(ISNULL((SELECT SUM(p.rows) FROM ClinicMasterMOH.sys.partitions p
                    WHERE p.object_id = t.object_id AND p.index_id IN (0,1)), 0) AS varchar(40))
FROM   ClinicMasterMOH.sys.tables t
WHERE  t.name LIKE '%Lab%' OR t.name LIKE '%Specimen%' OR t.name LIKE '%Test%'
    OR t.name LIKE '%Investigation%';

/* ---- 2. The join path: who else knows a SpecimenNo? ---------------
   A lab result is useless for HMIS until it can be tied to the visit that
   ordered it, because every lab cell on the form is broken down by age
   and sex. This asks which tables carry SpecimenNo, and which of those
   also carry something that reaches a patient.                        */
INSERT INTO #lab (section, item, detail, number)
SELECT '2_specimen_tables', t.name,
       CAST(LEFT(ISNULL(STUFF((SELECT ', ' + c2.name
                     FROM ClinicMasterMOH.sys.columns c2
                     WHERE c2.object_id = t.object_id
                       AND c2.name IN ('SpecimenNo','VisitNo','PatientNo','TreatmentNo',
                                       'ObjectName','RequestNo','LabNo','TestCode',
                                       'RequestDate','SpecimenDate','CollectionDate',
                                       'RecordDateTime')
                     ORDER BY c2.column_id
                     FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, ''), '(none)'), 380)
            AS varchar(400)),
       CAST(ISNULL((SELECT SUM(p.rows) FROM ClinicMasterMOH.sys.partitions p
                    WHERE p.object_id = t.object_id AND p.index_id IN (0,1)), 0) AS varchar(40))
FROM   ClinicMasterMOH.sys.tables t
WHERE  EXISTS (SELECT 1 FROM ClinicMasterMOH.sys.columns c
               WHERE c.object_id = t.object_id AND c.name = 'SpecimenNo');

/* ---- 2b. Does that join actually hold? ----------------------------
   A column of the same name is not a foreign key. For every table that
   carries both a SpecimenNo and a route to a patient, this counts how many
   of its specimens are present in INTLabResults. A high number means the
   join is real and lab results can be disaggregated; a zero means that
   table is a dead end and we look elsewhere.

   Dynamic SQL is used only because the table names are not known until
   section 2 has run. Every generated statement is a SELECT.            */
DECLARE @t sysname, @sql nvarchar(max);
DECLARE tbl CURSOR LOCAL FAST_FORWARD FOR
    SELECT t.name
    FROM   ClinicMasterMOH.sys.tables t
    WHERE  EXISTS (SELECT 1 FROM ClinicMasterMOH.sys.columns c
                   WHERE c.object_id = t.object_id AND c.name = 'SpecimenNo')
      AND  EXISTS (SELECT 1 FROM ClinicMasterMOH.sys.columns c
                   WHERE c.object_id = t.object_id
                     AND c.name IN ('VisitNo','PatientNo','TreatmentNo'))
      AND  t.name <> 'INTLabResults';
OPEN tbl;
FETCH NEXT FROM tbl INTO @t;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @sql = N'INSERT INTO #lab (section, item, detail, number)
                 SELECT ''2b_join_rate'', ' + QUOTENAME(@t, '''') + N',
                        ''of its specimens appear in INTLabResults'',
                        CAST(COUNT(DISTINCT s.SpecimenNo) AS varchar(40))
                 FROM   ClinicMasterMOH.dbo.' + QUOTENAME(@t) + N' s
                 WHERE  EXISTS (SELECT 1 FROM ClinicMasterMOH.dbo.INTLabResults r
                                WHERE r.SpecimenNo = s.SpecimenNo);';
    BEGIN TRY
        EXEC sp_executesql @sql;
    END TRY
    BEGIN CATCH
        INSERT INTO #lab (section, item, detail, number)
        VALUES ('2b_join_rate', @t, LEFT(ERROR_MESSAGE(), 380), '');
    END CATCH;
    FETCH NEXT FROM tbl INTO @t;
END
CLOSE tbl; DEALLOCATE tbl;

/* ---- 3. How far back the results go -------------------------------- */
INSERT INTO #lab (section, item, detail, number)
SELECT '3_coverage', 'INTLabResults.TestDateTime',
       CAST(CONVERT(varchar(10), MIN(TestDateTime), 23) + ' to ' +
            CONVERT(varchar(10), MAX(TestDateTime), 23) AS varchar(400)),
       CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabResults;

INSERT INTO #lab (section, item, detail, number)
SELECT '3_coverage', 'results per calendar year: ' +
       CAST(YEAR(ISNULL(TestDateTime, RecordDateTime)) AS varchar(4)), '',
       CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabResults
GROUP BY YEAR(ISNULL(TestDateTime, RecordDateTime));

/* ---- 4. Which tests, and how many of each -------------------------
   TestCode lives on the results; TestName lives on the requests. Joined
   here so the mapping table can be written against names a human can read
   and codes a machine can match.                                       */
INSERT INTO #lab (section, item, detail, number)
SELECT TOP 150 '4_tests',
       CAST(LEFT(r.TestCode + '  ' + ISNULL(nm.TestName, '(name not in requests)'), 380) AS varchar(400)),
       '', CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabResults r
LEFT JOIN (SELECT TestCode, MAX(TestName) AS TestName
           FROM ClinicMasterMOH.dbo.INTLabRequestDetails
           GROUP BY TestCode) nm ON nm.TestCode = r.TestCode
GROUP BY r.TestCode, nm.TestName
ORDER BY COUNT(*) DESC;

/* ---- 4b. The analyte level, for panels like a full blood count ----- */
INSERT INTO #lab (section, item, detail, number)
SELECT TOP 80 '4b_subtests',
       CAST(LEFT(ISNULL(e.SubTestCode, '(null)') + '  ' + ISNULL(e.SubTestName, ''), 380) AS varchar(400)),
       '', CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabResultsEXT e
GROUP BY e.SubTestCode, e.SubTestName
ORDER BY COUNT(*) DESC;

/* ---- 5. What a result looks like, for the reportable tests --------
   Values occurring fewer than five times are excluded, so nothing here
   could be traced to an individual episode.                            */
INSERT INTO #lab (section, item, detail, number)
SELECT TOP 120 '5_result_values',
       CAST(LEFT(r.TestCode + ' = ' + LEFT(ISNULL(r.Result, '(null)'), 100), 380) AS varchar(400)),
       CAST(LEFT(ISNULL(nm.TestName, ''), 380) AS varchar(400)),
       CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabResults r
JOIN  (SELECT TestCode, MAX(TestName) AS TestName
       FROM ClinicMasterMOH.dbo.INTLabRequestDetails
       GROUP BY TestCode) nm ON nm.TestCode = r.TestCode
WHERE  nm.TestName LIKE '%HIV%'      OR nm.TestName LIKE '%TB%'
    OR nm.TestName LIKE '%Xpert%'    OR nm.TestName LIKE '%Malaria%'
    OR nm.TestName LIKE '%MRDT%'     OR nm.TestName LIKE '%Syphilis%'
    OR nm.TestName LIKE '%Hep%'      OR nm.TestName LIKE '%Viral%'
    OR nm.TestName LIKE '%CD4%'      OR nm.TestName LIKE '%Crypto%'
    OR nm.TestName LIKE '%Culture%'  OR nm.TestName LIKE '%Sputum%'
GROUP BY r.TestCode, LEFT(ISNULL(r.Result, '(null)'), 100), nm.TestName
HAVING COUNT(*) >= 5
ORDER BY COUNT(*) DESC;

/* ---- 6. The flag column, which may be the tidy version of the above  */
INSERT INTO #lab (section, item, detail, number)
SELECT '6_result_flags', CAST(LEFT(ISNULL(ResultFlagID, '(null)'), 380) AS varchar(400)), '',
       CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabResults
GROUP BY ResultFlagID;

/* ---- 7. Integration configuration - COLUMN NAMES ONLY --------------
   INTAgents holds seven rows describing the configured integrations. It
   very likely contains the ALIS endpoint and a credential. The credential
   is not needed here and must not be pasted anywhere, so this reads the
   catalogue rather than the table.                                     */
INSERT INTO #lab (section, item, detail, number)
SELECT '7_intagents_columns', 'INTAgents',
       CAST(LEFT(STUFF((SELECT ', ' + c.name
                        FROM ClinicMasterMOH.sys.columns c
                        WHERE c.object_id = t.object_id
                        ORDER BY c.column_id
                        FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, ''), 380)
            AS varchar(400)), ''
FROM   ClinicMasterMOH.sys.tables t
WHERE  t.name = 'INTAgents';

/* ---- 8. How results arrive: pushed by ALIS, or pulled by us? -------
   If SyncStatus and RecordDateTime show results landing in batches long
   after the request, ClinicMaster is polling. That matters, because a
   polling client already exists and we should extend it rather than build
   a second one.                                                        */
INSERT INTO #lab (section, item, detail, number)
SELECT '8_result_sync', 'SyncStatus ' + CAST(ISNULL(CAST(SyncStatus AS varchar(10)), '(null)') AS varchar(10)),
       '', CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabResults
GROUP BY SyncStatus;

INSERT INTO #lab (section, item, detail, number)
SELECT TOP 10 '8_result_sync', 'error: ' + CAST(LEFT(ISNULL(ErrorMessage, '(none)'), 200) AS varchar(280)),
       '', CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabResults
GROUP BY CAST(LEFT(ISNULL(ErrorMessage, '(none)'), 200) AS varchar(280))
ORDER BY COUNT(*) DESC;

/* Ordered by insertion, so that within each section the busiest tests and
   the commonest result values stay at the top where they are useful. */
SELECT section, item, detail, number FROM #lab ORDER BY section, seq;

DROP TABLE #lab;
