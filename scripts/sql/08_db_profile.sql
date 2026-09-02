/* ==================================================================
   CLINICMASTER PROFILE - everything needed to write the report queries
   ------------------------------------------------------------------
   Server   : 172.20.0.230        Database: ClinicMasterMOH

   SAFETY   : Read-only. Catalogue views, distinct-value counts and
              aggregate totals. Sample values are shown ONLY for columns
              with 25 or fewer distinct values - those are lookup codes,
              never free text or a patient detail. No name, number or
              date of birth is read anywhere in this script.

   USAGE    : Run the whole thing in one go. It returns ONE result grid
              of roughly 60-80 short rows. Select all, copy, paste back.

   ANSWERS  : - the OPD/IPD discriminator column in Diagnosis
              - whether Diseases carries an ICD-11 code, and how full it is
              - how Diagnosis links to Visits and to Diseases
              - diagnoses per visit for a real, complete month
              - the visit category and status vocabularies
   ================================================================== */

SET NOCOUNT ON;

DECLARE @DB sysname = N'ClinicMasterMOH';

IF OBJECT_ID('tempdb..#out') IS NOT NULL DROP TABLE #out;
CREATE TABLE #out (
    section varchar(30),
    item    varchar(200),
    detail  varchar(4000),
    number  varchar(60)
);

/* ---- 1. Column lists for the tables the queries will read --------- */
INSERT INTO #out (section, item, detail, number)
SELECT '1_columns', t.name,
       CAST(STUFF((SELECT ', ' + c.name + ' [' + ty.name + ']'
                   FROM ClinicMasterMOH.sys.columns c
                   JOIN ClinicMasterMOH.sys.types ty ON ty.user_type_id = c.user_type_id
                   WHERE c.object_id = t.object_id
                   ORDER BY c.column_id
                   FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '')
            AS varchar(4000)),
       CAST(ISNULL((SELECT SUM(p.rows) FROM ClinicMasterMOH.sys.partitions p
                    WHERE p.object_id = t.object_id AND p.index_id IN (0,1)), 0)
            AS varchar(60))
FROM   ClinicMasterMOH.sys.tables t
WHERE  t.name IN ('Diagnosis', 'Diseases', 'Visits', 'Patients',
                  'ArchivedOPDDiagnosis', 'ArchiveIPDDiagnosis', 'Items');

/* ---- 2. Every column of Diagnosis and Diseases, by cardinality ----
   A column with two or three distinct values across 278,000 rows is a
   flag - this is how the OPD/IPD discriminator will announce itself.
   A column with tens of thousands is an identifier or a code.        */
DECLARE @t sysname, @c sysname, @ty sysname, @sql nvarchar(max), @n bigint, @vals nvarchar(max);

DECLARE col_cur CURSOR LOCAL FAST_FORWARD FOR
    SELECT t.name, c.name, ty.name
    FROM   ClinicMasterMOH.sys.columns c
    JOIN   ClinicMasterMOH.sys.tables  t  ON t.object_id = c.object_id
    JOIN   ClinicMasterMOH.sys.types   ty ON ty.user_type_id = c.user_type_id
    WHERE  t.name IN ('Diagnosis', 'Diseases')
      AND  ty.name NOT IN ('text','ntext','image','xml','varbinary','binary',
                           'geography','geometry','hierarchyid')
    ORDER BY t.name, c.column_id;

OPEN col_cur;
FETCH NEXT FROM col_cur INTO @t, @c, @ty;

WHILE @@FETCH_STATUS = 0
BEGIN
    SET @n = NULL;
    SET @vals = NULL;

    BEGIN TRY
        SET @sql = N'SELECT @out = COUNT(DISTINCT ' + QUOTENAME(@c) + N')
                     FROM ' + QUOTENAME(@DB) + N'.dbo.' + QUOTENAME(@t);
        EXEC sp_executesql @sql, N'@out bigint OUTPUT', @out = @n OUTPUT;
    END TRY
    BEGIN CATCH
        SET @n = NULL;
    END CATCH;

    /* Only sample where the column is plainly a lookup. 25 or fewer
       distinct values cannot be free text or a patient detail.        */
    IF @n IS NOT NULL AND @n BETWEEN 1 AND 25
    BEGIN
        BEGIN TRY
            SET @sql = N'SELECT @out = STUFF((SELECT DISTINCT TOP 25
                                '' | '' + CAST(' + QUOTENAME(@c) + N' AS varchar(60))
                            FROM ' + QUOTENAME(@DB) + N'.dbo.' + QUOTENAME(@t) + N'
                            WHERE ' + QUOTENAME(@c) + N' IS NOT NULL
                            FOR XML PATH(''''), TYPE).value(''.'', ''nvarchar(max)''), 1, 3, '''')';
            EXEC sp_executesql @sql, N'@out nvarchar(max) OUTPUT', @out = @vals OUTPUT;
        END TRY
        BEGIN CATCH
            SET @vals = '(could not sample)';
        END CATCH;
    END

    /* How full is it? A code column that is 95 per cent NULL is not
       usable for mapping, however promising its name.                 */
    DECLARE @filled bigint = NULL;
    BEGIN TRY
        SET @sql = N'SELECT @out = COUNT(' + QUOTENAME(@c) + N')
                     FROM ' + QUOTENAME(@DB) + N'.dbo.' + QUOTENAME(@t);
        EXEC sp_executesql @sql, N'@out bigint OUTPUT', @out = @filled OUTPUT;
    END TRY
    BEGIN CATCH
        SET @filled = NULL;
    END CATCH;

    INSERT INTO #out (section, item, detail, number)
    VALUES ('2_' + @t,
            @c + '  [' + @ty + ']',
            LEFT(ISNULL(@vals, ''), 3900),
            'distinct=' + ISNULL(CAST(@n AS varchar(20)), '?')
              + '  nonnull=' + ISNULL(CAST(@filled AS varchar(20)), '?'));

    FETCH NEXT FROM col_cur INTO @t, @c, @ty;
END

CLOSE col_cur;
DEALLOCATE col_cur;

/* ---- 3. Diagnoses per visit, over one complete recent month -------
   The all-time ratio is misleading because Visits reaches back to 1910
   while Diagnosis may not. This measures a month where both are live. */
DECLARE @mstart date = DATEFROMPARTS(YEAR(DATEADD(month, -2, GETDATE())),
                                     MONTH(DATEADD(month, -2, GETDATE())), 1);
DECLARE @mend   date = DATEADD(month, 1, @mstart);

INSERT INTO #out (section, item, detail, number)
SELECT '3_ratio', 'month measured',
       CONVERT(varchar(10), @mstart, 23) + ' to ' + CONVERT(varchar(10), @mend, 23), '';

INSERT INTO #out (section, item, detail, number)
SELECT '3_ratio', 'visits in that month', '', CAST(COUNT(*) AS varchar(60))
FROM   ClinicMasterMOH.dbo.Visits
WHERE  VisitDate >= @mstart AND VisitDate < @mend;

INSERT INTO #out (section, item, detail, number)
SELECT '3_ratio', 'distinct patients in that month', '',
       CAST(COUNT(DISTINCT PatientNo) AS varchar(60))
FROM   ClinicMasterMOH.dbo.Visits
WHERE  VisitDate >= @mstart AND VisitDate < @mend;

/* ---- 4. Date coverage --------------------------------------------- */
INSERT INTO #out (section, item, detail, number)
SELECT '4_coverage', 'Visits.VisitDate',
       CONVERT(varchar(10), MIN(VisitDate), 23) + ' to ' + CONVERT(varchar(10), MAX(VisitDate), 23),
       CAST(COUNT(*) AS varchar(60))
FROM   ClinicMasterMOH.dbo.Visits;

/* ---- 5. Visit vocabularies, last six months ----------------------- */
INSERT INTO #out (section, item, detail, number)
SELECT '5_visit_category', CAST(ISNULL(VisitCategoryID, '(null)') AS varchar(200)), '',
       CAST(COUNT(*) AS varchar(60))
FROM   ClinicMasterMOH.dbo.Visits
WHERE  VisitDate >= DATEADD(month, -6, GETDATE())
GROUP BY VisitCategoryID;

INSERT INTO #out (section, item, detail, number)
SELECT '6_visit_status', CAST(ISNULL(VisitStatusID, '(null)') AS varchar(200)), '',
       CAST(COUNT(*) AS varchar(60))
FROM   ClinicMasterMOH.dbo.Visits
WHERE  VisitDate >= DATEADD(month, -6, GETDATE())
GROUP BY VisitStatusID;

INSERT INTO #out (section, item, detail, number)
SELECT '7_gender', CAST(ISNULL(GenderID, '(null)') AS varchar(200)), '',
       CAST(COUNT(*) AS varchar(60))
FROM   ClinicMasterMOH.dbo.Patients
GROUP BY GenderID;

/* ---- 6. Every diagnosis-ish table, for completeness --------------- */
INSERT INTO #out (section, item, detail, number)
SELECT '8_all_diagnosis_tables', t.name, '',
       CAST(ISNULL((SELECT SUM(p.rows) FROM ClinicMasterMOH.sys.partitions p
                    WHERE p.object_id = t.object_id AND p.index_id IN (0,1)), 0)
            AS varchar(60))
FROM   ClinicMasterMOH.sys.tables t
WHERE  t.name LIKE '%diagnos%' OR t.name LIKE '%disease%';

/* ---- OUTPUT: one grid -------------------------------------------- */
SELECT section, item, detail, number
FROM   #out
ORDER BY section, item;

DROP TABLE #out;
