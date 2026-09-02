/* ==================================================================
   LAB - RESULT VOCABULARY AND THE ROUTE BACK TO A VISIT   (v2)
   ------------------------------------------------------------------
   Server   : 172.20.0.230        Database: ClinicMasterMOH

   WHY THIS IS VERSION TWO
   Version one referenced LabResultsEXT.SubTestName, which does not
   exist - I assumed the clinical table mirrored the INT staging table,
   and it does not. The whole script then failed, including the six
   sections that were correct, because an invalid column name is a
   COMPILE-time binding error: SQL Server binds the entire batch before
   running any of it, so TRY/CATCH never got the chance to catch
   anything. Wrapping a static query in TRY/CATCH protects against
   runtime failures only. It is no protection at all against a column
   name I guessed wrong.

   So this version does not guess. Section 1 reads the real columns from
   the catalogue, and every section after it is built as dynamic SQL from
   what is actually there. Dynamic SQL is compiled when it is executed,
   inside the TRY, which is what makes the guard work. Where a column may
   or may not exist, COL_LENGTH decides which expression to build.

   WHAT SCRIPT 11 SETTLED
   The join works: LabRequests carries SpecimenNo and VisitNo, and 28,191
   of 28,214 results reconcile to it - 99.9 per cent.

   And the result value is not on the parent row. LabResults.Result is
   blank for every reportable test: 3,724 empty malaria smears, 222 empty
   HIV serologies. The value lives one level down, in LabResultsEXT. The
   give-away was in script 11's own output - sub-test '01 Detection'
   appears exactly 3,724 times, matching the blank malaria parents one
   for one.

   SAFETY
   Result values are grouped and filtered to those occurring five times
   or more, so no value here can be tied to an individual episode. No
   specimen number, patient number, name or date of birth is returned.
   Binary and large-object columns are excluded from the generic dumps.

   USAGE : Run the whole script. It returns ONE grid.
   ================================================================== */

SET NOCOUNT ON;

IF OBJECT_ID('tempdb..#v') IS NOT NULL DROP TABLE #v;
CREATE TABLE #v (seq int IDENTITY(1,1), section varchar(40), item varchar(400),
                 detail varchar(400), number varchar(40));

DECLARE @sql nvarchar(max), @cols nvarchar(max), @lbl nvarchar(200),
        @tbl sysname, @sec varchar(40);

/* ---- 1. The real columns. Catalogue only, so this cannot fail ------ */
INSERT INTO #v (section, item, detail, number)
SELECT '1_columns', t.name,
       CAST(LEFT(STUFF((SELECT ', ' + c.name
                        FROM ClinicMasterMOH.sys.columns c
                        WHERE c.object_id = t.object_id
                        ORDER BY c.column_id
                        FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, ''), 380)
            AS varchar(400)),
       CAST(ISNULL((SELECT SUM(p.rows) FROM ClinicMasterMOH.sys.partitions p
                    WHERE p.object_id = t.object_id AND p.index_id IN (0,1)), 0) AS varchar(40))
FROM   ClinicMasterMOH.sys.tables t
WHERE  t.name IN ('LabRequests', 'LabRequestsIPD', 'LabRequestDetails', 'LabResults',
                  'LabResultsEXT', 'LabTests', 'LabTestsEXT', 'LabPossibleResults',
                  'LabTestsEXTPossibleResults', 'LabTestsEXTMappings', 'HTSTesting',
                  'PreTestingCounseling', 'PostTestingCounseling', 'HIVEligibilityTesting');

/* ---- 2. Small reference tables, dumped whatever their shape --------
   The sub-test catalogue is the one that matters: LabResultsEXT holds a
   SubTestCode but, as we now know, no name for it. LabTestsEXT (168
   rows) is where '01 Detection' and its siblings are defined.          */
DECLARE dmp CURSOR LOCAL FAST_FORWARD FOR
    SELECT v.t, v.s FROM (VALUES
        ('LabPossibleResults',         '2_possible_results'),
        ('LabTestsEXTPossibleResults', '2b_subtest_possible'),
        ('LabTests',                   '5_test_catalogue'),
        ('LabTestsEXT',                '5b_subtest_catalogue'),
        ('LabTestsEXTMappings',        '5c_subtest_mappings')) v(t, s);
OPEN dmp;
FETCH NEXT FROM dmp INTO @tbl, @sec;
WHILE @@FETCH_STATUS = 0
BEGIN
    BEGIN TRY
        SELECT @cols = ISNULL((
            SELECT ' + '' | '' + ISNULL(CONVERT(varchar(100), ' + QUOTENAME(c.name) + N'), '''')'
            FROM   ClinicMasterMOH.sys.columns c
            JOIN   ClinicMasterMOH.sys.types  ty ON ty.user_type_id = c.user_type_id
            WHERE  c.object_id = OBJECT_ID('ClinicMasterMOH.dbo.' + @tbl)
              AND  ty.name NOT IN ('image','text','ntext','xml','varbinary','binary',
                                   'geography','geometry','hierarchyid','timestamp','sql_variant')
            ORDER BY c.column_id
            FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), N'');
        IF @cols <> N''
        BEGIN
            /* Four quotes produce an empty string literal in the generated
               SQL, which gives the leading concatenation something to
               attach to and saves trimming the expression. */
            SET @sql = N'INSERT INTO #v (section, item, detail, number)
                         SELECT TOP 250 ''' + @sec + N''',
                                CAST(LEFT('''' ' + @cols + N', 380) AS varchar(400)), '''', ''''
                         FROM ClinicMasterMOH.dbo.' + QUOTENAME(@tbl) + N';';
            EXEC sp_executesql @sql;
        END
    END TRY
    BEGIN CATCH
        INSERT INTO #v (section, item, detail, number)
        VALUES (@sec, @tbl, LEFT(ERROR_MESSAGE(), 380), '');
    END CATCH;
    FETCH NEXT FROM dmp INTO @tbl, @sec;
END
CLOSE dmp; DEALLOCATE dmp;

/* ---- 3. THE ANSWER WE NEED: what a result looks like ---------------
   Read from the analyte table. The label column is chosen from what
   exists rather than assumed, which is the mistake version one made. */
BEGIN TRY
    IF COL_LENGTH('ClinicMasterMOH.dbo.LabResultsEXT', 'Result') IS NOT NULL
    BEGIN
        SET @lbl = CASE
            WHEN COL_LENGTH('ClinicMasterMOH.dbo.LabResultsEXT', 'SubTestName') IS NOT NULL
                 THEN N'ISNULL(e.SubTestName, e.SubTestCode)'
            WHEN COL_LENGTH('ClinicMasterMOH.dbo.LabResultsEXT', 'SubTestCode') IS NOT NULL
                 THEN N'e.SubTestCode'
            ELSE N'e.TestCode' END;

        SET @sql = N'
        INSERT INTO #v (section, item, detail, number)
        SELECT TOP 150 ''3_result_values'',
               CAST(LEFT(CONVERT(varchar(80), ' + @lbl + N') + ''  ->  ''
                         + LEFT(ISNULL(NULLIF(LTRIM(RTRIM(e.Result)), ''''), ''(blank)''), 60),
                         380) AS varchar(400)),
               CAST(LEFT(ISNULL(t.TestName, ''''), 380) AS varchar(400)),
               CAST(COUNT(*) AS varchar(40))
        FROM   ClinicMasterMOH.dbo.LabResultsEXT e
        LEFT JOIN (SELECT TestCode, MAX(TestName) AS TestName
                   FROM ClinicMasterMOH.dbo.INTLabRequestDetails GROUP BY TestCode) t
               ON t.TestCode = e.TestCode
        WHERE  e.TestCode IN (''372071003'',''407727009'',''165813002'',''313660005'',
                              ''9000001'',''951277'',''121980003'',''47758006'',
                              ''269829001'',''19869000'',''399256002'',''315124004'',
                              ''28804003'',''40675008'',''67900009'',''LAB010'',
                              ''406979008'',''252390002'',''83033005'')
        GROUP BY CONVERT(varchar(80), ' + @lbl + N'),
                 LEFT(ISNULL(NULLIF(LTRIM(RTRIM(e.Result)), ''''), ''(blank)''), 60), t.TestName
        HAVING COUNT(*) >= 5
        ORDER BY COUNT(*) DESC;';
        EXEC sp_executesql @sql;
    END
    ELSE
        INSERT INTO #v (section, item, detail, number)
        VALUES ('3_result_values', 'LabResultsEXT has no Result column',
                'see section 1 for what it does have', '');
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('3_result_values', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 4. Confirm the parent really is empty ------------------------- */
BEGIN TRY
    SET @sql = N'
    INSERT INTO #v (section, item, detail, number)
    SELECT ''4_parent_vs_child'', ''LabResults rows with a non-blank Result'', '''',
           CAST(SUM(CASE WHEN NULLIF(LTRIM(RTRIM(ISNULL(Result, ''''))), '''') IS NOT NULL
                         THEN 1 ELSE 0 END) AS varchar(40))
    FROM ClinicMasterMOH.dbo.LabResults;
    INSERT INTO #v (section, item, detail, number)
    SELECT ''4_parent_vs_child'', ''LabResultsEXT rows with a non-blank Result'', '''',
           CAST(SUM(CASE WHEN NULLIF(LTRIM(RTRIM(ISNULL(Result, ''''))), '''') IS NOT NULL
                         THEN 1 ELSE 0 END) AS varchar(40))
    FROM ClinicMasterMOH.dbo.LabResultsEXT;';
    EXEC sp_executesql @sql;
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('4_parent_vs_child', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 6. The OPD join, quantified by year --------------------------
   How many results in each year can be traced to a visit. A result we
   cannot place has no age and no sex and cannot be reported.          */
BEGIN TRY
    SET @sql = N'
    INSERT INTO #v (section, item, detail, number)
    SELECT ''6_join_by_year'',
           CAST(YEAR(r.RecordDateTime) AS varchar(4)) + '': traceable to a visit'', '''',
           CAST(SUM(CASE WHEN v.VisitNo IS NOT NULL THEN 1 ELSE 0 END) AS varchar(40))
    FROM   ClinicMasterMOH.dbo.LabResults r
    LEFT JOIN ClinicMasterMOH.dbo.LabRequests q ON q.SpecimenNo = r.SpecimenNo
    LEFT JOIN ClinicMasterMOH.dbo.Visits      v ON v.VisitNo    = q.VisitNo
    GROUP BY YEAR(r.RecordDateTime);
    INSERT INTO #v (section, item, detail, number)
    SELECT ''6_join_by_year'',
           CAST(YEAR(r.RecordDateTime) AS varchar(4)) + '': NO visit found'', '''',
           CAST(SUM(CASE WHEN v.VisitNo IS NULL THEN 1 ELSE 0 END) AS varchar(40))
    FROM   ClinicMasterMOH.dbo.LabResults r
    LEFT JOIN ClinicMasterMOH.dbo.LabRequests q ON q.SpecimenNo = r.SpecimenNo
    LEFT JOIN ClinicMasterMOH.dbo.Visits      v ON v.VisitNo    = q.VisitNo
    GROUP BY YEAR(r.RecordDateTime);';
    EXEC sp_executesql @sql;
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('6_join_by_year', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 7. How inpatient lab requests attach --------------------------
   LabRequestsIPD carries a specimen but no VisitNo, so it reaches the
   patient some other way. Section 1 names its columns; this sizes it. */
BEGIN TRY
    SET @sql = N'
    INSERT INTO #v (section, item, detail, number)
    SELECT ''7_ipd'', ''LabRequestsIPD rows'', '''', CAST(COUNT(*) AS varchar(40))
    FROM ClinicMasterMOH.dbo.LabRequestsIPD;
    INSERT INTO #v (section, item, detail, number)
    SELECT ''7_ipd'', ''its specimens that have a result'', '''',
           CAST(COUNT(DISTINCT q.SpecimenNo) AS varchar(40))
    FROM ClinicMasterMOH.dbo.LabRequestsIPD q
    WHERE EXISTS (SELECT 1 FROM ClinicMasterMOH.dbo.LabResults r
                  WHERE r.SpecimenNo = q.SpecimenNo);';
    EXEC sp_executesql @sql;
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('7_ipd', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 8. The 66 stuck results ---------------------------------------
   uspUpdateLabResults expects @DateResultsReceived and is not given it.
   These are results that came back from CPHL and never attached to the
   clinical record. When, and for which tests.                         */
BEGIN TRY
    SET @sql = N'
    INSERT INTO #v (section, item, detail, number)
    SELECT ''8_stuck'', ''test '' + CAST(ISNULL(TestCode, ''?'') AS varchar(40)),
           CAST(CONVERT(varchar(10), MIN(RecordDateTime), 23) + '' to '' +
                CONVERT(varchar(10), MAX(RecordDateTime), 23) AS varchar(400)),
           CAST(COUNT(*) AS varchar(40))
    FROM ClinicMasterMOH.dbo.INTLabResults
    WHERE SyncStatus = 0
    GROUP BY TestCode;';
    EXEC sp_executesql @sql;
END TRY
BEGIN CATCH
    INSERT INTO #v (section, item, detail, number)
    VALUES ('8_stuck', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

SELECT section, item, detail, number FROM #v ORDER BY section, seq;

DROP TABLE #v;
