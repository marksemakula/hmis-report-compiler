/* ==================================================================
   LAB — RESULT VOCABULARY AND THE ROUTE BACK TO A VISIT
   ------------------------------------------------------------------
   Server   : 172.20.0.230        Database: ClinicMasterMOH

   WHAT SCRIPT 11 SETTLED
   The join works. LabRequests carries both SpecimenNo and VisitNo, and
   28,191 of the 28,214 results reconcile to it — 99.9 per cent. Lab
   figures can therefore be disaggregated by age and sex like any other
   HMIS cell.

   WHAT SCRIPT 11 GOT WRONG, AND WHY
   Section 5 asked LabResults.Result for the result value and got blanks:
   3,724 empty malaria smears, 222 empty HIV serologies. That was my
   error. The parent row is a container; the value lives one level down in
   LabResultsEXT, one row per analyte. The give-away is in the same output
   — sub-test '01 Detection' appears exactly 3,724 times, matching the
   3,724 blank malaria parents one for one.

   This script reads the vocabulary from the child table, where it is.

   TWO FURTHER CORRECTIONS
   LabPossibleResults holds 43 rows. If that is the controlled vocabulary
   ClinicMaster offers the laboratory, it beats anything inferred from
   observed data, because it includes values that are permitted but have
   not yet occurred. Section 2 reads it whatever its shape turns out to be.

   And the INT-prefixed tables are integration staging. The unprefixed
   ones are ClinicMaster's clinical record, and hold fourteen results the
   integration never carried. The compiler should read the clinical
   tables, so this script does.

   SAFETY
   Result values are grouped and filtered to those occurring five times or
   more, so no value here can be tied to an individual episode. No
   specimen number, patient number, name or date of birth is returned.

   ROBUSTNESS
   Every section is wrapped, because the exact column names of the
   unprefixed tables are still inferred rather than confirmed. A section
   that guesses wrong reports its error into the grid and the rest still
   runs — one wrong guess should not cost a whole round trip.

   USAGE : Run the whole script. It returns ONE grid.
   ================================================================== */

SET NOCOUNT ON;

IF OBJECT_ID('tempdb..#v') IS NOT NULL DROP TABLE #v;
CREATE TABLE #v (seq int IDENTITY(1,1), section varchar(40), item varchar(400),
                 detail varchar(400), number varchar(40));

DECLARE @sql nvarchar(max), @cols nvarchar(max);

/* ---- 1. The columns of every table we are about to rely on --------- */
BEGIN TRY
    INSERT INTO #v (section, item, detail, number)
    SELECT '1_columns', t.name,
           CAST(LEFT(STUFF((SELECT ', ' + c.name
                            FROM ClinicMasterMOH.sys.columns c
                            WHERE c.object_id = t.object_id
                            ORDER BY c.column_id
                            FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, ''), 380)
                AS varchar(400)), ''
    FROM   ClinicMasterMOH.sys.tables t
    WHERE  t.name IN ('LabRequests', 'LabRequestsIPD', 'LabRequestDetails', 'LabResults',
                      'LabResultsEXT', 'LabTests', 'LabTestsEXT', 'LabPossibleResults',
                      'LabTestsEXTPossibleResults', 'LabTestsEXTMappings', 'HTSTesting',
                      'PreTestingCounseling', 'PostTestingCounseling', 'HIVEligibilityTesting');
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('1_columns', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 2. The controlled vocabulary, read whatever its shape ---------
   The column names are not known until section 1 has run, so the row
   text is assembled from sys.columns. Starting the expression with an
   empty literal means the generated concatenation needs no trimming. */
BEGIN TRY
    SELECT @cols = ISNULL((SELECT ' + '' | '' + ISNULL(CONVERT(varchar(100), ' + QUOTENAME(c.name) + N'), '''')'
                           FROM ClinicMasterMOH.sys.columns c
                           WHERE c.object_id = OBJECT_ID('ClinicMasterMOH.dbo.LabPossibleResults')
                           ORDER BY c.column_id
                           FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), N'');
    IF @cols <> N''
    BEGIN
        SET @sql = N'INSERT INTO #v (section, item, detail, number)
                     SELECT ''2_vocabulary'', CAST(LEFT('''''''' ' + @cols + N', 380) AS varchar(400)), '''', ''''
                     FROM ClinicMasterMOH.dbo.LabPossibleResults;';
        EXEC sp_executesql @sql;
    END
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('2_vocabulary', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 2b. And the sub-test vocabulary, same treatment --------------- */
BEGIN TRY
    SELECT @cols = ISNULL((SELECT ' + '' | '' + ISNULL(CONVERT(varchar(100), ' + QUOTENAME(c.name) + N'), '''')'
                           FROM ClinicMasterMOH.sys.columns c
                           WHERE c.object_id = OBJECT_ID('ClinicMasterMOH.dbo.LabTestsEXTPossibleResults')
                           ORDER BY c.column_id
                           FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), N'');
    IF @cols <> N''
    BEGIN
        SET @sql = N'INSERT INTO #v (section, item, detail, number)
                     SELECT ''2b_subtest_vocab'', CAST(LEFT('''''''' ' + @cols + N', 380) AS varchar(400)), '''', ''''
                     FROM ClinicMasterMOH.dbo.LabTestsEXTPossibleResults;';
        EXEC sp_executesql @sql;
    END
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('2b_subtest_vocab', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 3. THE ANSWER WE ACTUALLY NEED -------------------------------
   What a result looks like, read from the analyte table where the values
   live. Grouped, and filtered to five occurrences or more. Test names
   come from INTLabRequestDetails, which script 11 proved carries them. */
BEGIN TRY
    INSERT INTO #v (section, item, detail, number)
    SELECT TOP 150 '3_result_values',
           CAST(LEFT(ISNULL(e.SubTestName, e.SubTestCode) + '  ->  '
                     + LEFT(ISNULL(NULLIF(LTRIM(RTRIM(e.Result)), ''), '(blank)'), 60), 380) AS varchar(400)),
           CAST(LEFT(ISNULL(t.TestName, ''), 380) AS varchar(400)),
           CAST(COUNT(*) AS varchar(40))
    FROM   ClinicMasterMOH.dbo.LabResultsEXT e
    LEFT JOIN (SELECT TestCode, MAX(TestName) AS TestName
               FROM ClinicMasterMOH.dbo.INTLabRequestDetails GROUP BY TestCode) t
           ON t.TestCode = e.TestCode
    WHERE  e.TestCode IN ('372071003','407727009','165813002','313660005','9000001',
                          '951277','121980003','47758006','269829001','19869000',
                          '399256002','315124004','28804003','40675008','67900009',
                          'LAB010','406979008','252390002','83033005')
    GROUP BY ISNULL(e.SubTestName, e.SubTestCode),
             LEFT(ISNULL(NULLIF(LTRIM(RTRIM(e.Result)), ''), '(blank)'), 60), t.TestName
    HAVING COUNT(*) >= 5
    ORDER BY COUNT(*) DESC;
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('3_result_values', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 4. Confirm the parent really is empty ------------------------- */
BEGIN TRY
    INSERT INTO #v (section, item, detail, number)
    SELECT '4_parent_vs_child', 'LabResults rows with a non-blank Result', '',
           CAST(SUM(CASE WHEN NULLIF(LTRIM(RTRIM(ISNULL(Result, ''))), '') IS NOT NULL
                         THEN 1 ELSE 0 END) AS varchar(40))
    FROM   ClinicMasterMOH.dbo.LabResults;

    INSERT INTO #v (section, item, detail, number)
    SELECT '4_parent_vs_child', 'LabResultsEXT rows with a non-blank Result', '',
           CAST(SUM(CASE WHEN NULLIF(LTRIM(RTRIM(ISNULL(Result, ''))), '') IS NOT NULL
                         THEN 1 ELSE 0 END) AS varchar(40))
    FROM   ClinicMasterMOH.dbo.LabResultsEXT;
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('4_parent_vs_child', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 5. The full test catalogue, read whatever its shape ----------- */
BEGIN TRY
    SELECT @cols = ISNULL((SELECT ' + '' | '' + ISNULL(CONVERT(varchar(100), ' + QUOTENAME(c.name) + N'), '''')'
                           FROM ClinicMasterMOH.sys.columns c
                           WHERE c.object_id = OBJECT_ID('ClinicMasterMOH.dbo.LabTests')
                             AND c.name NOT IN ('Photo', 'Fingerprint')
                           ORDER BY c.column_id
                           FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), N'');
    IF @cols <> N''
    BEGIN
        SET @sql = N'INSERT INTO #v (section, item, detail, number)
                     SELECT ''5_test_catalogue'', CAST(LEFT('''''''' ' + @cols + N', 380) AS varchar(400)), '''', ''''
                     FROM ClinicMasterMOH.dbo.LabTests;';
        EXEC sp_executesql @sql;
    END
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('5_test_catalogue', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 6. The OPD join, quantified by year --------------------------
   How many results in each year can be traced to a visit. A result we
   cannot place has no age and no sex and cannot be reported. Dated by
   RecordDateTime, which section 11 confirmed exists on LabResults.     */
BEGIN TRY
    INSERT INTO #v (section, item, detail, number)
    SELECT '6_join_by_year',
           CAST(YEAR(r.RecordDateTime) AS varchar(4)) + ': traceable to a visit', '',
           CAST(SUM(CASE WHEN v.VisitNo IS NOT NULL THEN 1 ELSE 0 END) AS varchar(40))
    FROM   ClinicMasterMOH.dbo.LabResults r
    LEFT JOIN ClinicMasterMOH.dbo.LabRequests q ON q.SpecimenNo = r.SpecimenNo
    LEFT JOIN ClinicMasterMOH.dbo.Visits      v ON v.VisitNo    = q.VisitNo
    GROUP BY YEAR(r.RecordDateTime);

    INSERT INTO #v (section, item, detail, number)
    SELECT '6_join_by_year',
           CAST(YEAR(r.RecordDateTime) AS varchar(4)) + ': NO visit found', '',
           CAST(SUM(CASE WHEN v.VisitNo IS NULL THEN 1 ELSE 0 END) AS varchar(40))
    FROM   ClinicMasterMOH.dbo.LabResults r
    LEFT JOIN ClinicMasterMOH.dbo.LabRequests q ON q.SpecimenNo = r.SpecimenNo
    LEFT JOIN ClinicMasterMOH.dbo.Visits      v ON v.VisitNo    = q.VisitNo
    GROUP BY YEAR(r.RecordDateTime);
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('6_join_by_year', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 7. How inpatient lab requests attach -------------------------- */
BEGIN TRY
    INSERT INTO #v (section, item, detail, number)
    SELECT '7_ipd', 'LabRequestsIPD rows', '', CAST(COUNT(*) AS varchar(40))
    FROM   ClinicMasterMOH.dbo.LabRequestsIPD;

    INSERT INTO #v (section, item, detail, number)
    SELECT '7_ipd', 'its specimens that have a result', '',
           CAST(COUNT(DISTINCT q.SpecimenNo) AS varchar(40))
    FROM   ClinicMasterMOH.dbo.LabRequestsIPD q
    WHERE  EXISTS (SELECT 1 FROM ClinicMasterMOH.dbo.LabResults r
                   WHERE r.SpecimenNo = q.SpecimenNo);
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('7_ipd', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 8. The 66 stuck results ---------------------------------------
   Script 11 found 66 results failing on a stored-procedure signature:
   uspUpdateLabResults expects @DateResultsReceived and is not being given
   it. Those are laboratory results that came back from CPHL and never
   attached to the clinical record. When, and for which tests.          */
BEGIN TRY
    INSERT INTO #v (section, item, detail, number)
    SELECT '8_stuck', 'test ' + CAST(ISNULL(TestCode, '?') AS varchar(40)),
           CAST(CONVERT(varchar(10), MIN(RecordDateTime), 23) + ' to ' +
                CONVERT(varchar(10), MAX(RecordDateTime), 23) AS varchar(400)),
           CAST(COUNT(*) AS varchar(40))
    FROM   ClinicMasterMOH.dbo.INTLabResults
    WHERE  SyncStatus = 0
    GROUP BY TestCode;
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('8_stuck', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

SELECT section, item, detail, number FROM #v ORDER BY section, seq;

DROP TABLE #v;
