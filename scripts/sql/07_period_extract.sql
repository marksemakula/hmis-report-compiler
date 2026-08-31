/* ==================================================================
   HMIS REPORT COMPILER — PERIOD EXTRACT (WEEKLY OR MONTHLY)
   ------------------------------------------------------------------
   Server   : 172.20.0.230
   Database : ClinicMasterMOH

   PURPOSE  : Emit a two-column tally (Code, Value) in exactly the shape
              the compiler's 033B importer expects. Set @PeriodType to
              'W' for the weekly surveillance report or 'M' for a
              monthly run of the same indicators.

   SAFETY   : Strictly read-only. Aggregate counts only - no patient
              identifiers appear in the output.

   USAGE    : Set the three variables below, execute, then export the
              grid as CSV and upload it in the compiler.

              Weekly : @PeriodType='W', @Year=2026, @Period=35
              Monthly: @PeriodType='M', @Year=2026, @Period=8

   ISO WEEKS: DHIS2's Weekly period type is ISO-8601 - weeks run Monday
              to Sunday and week 1 is the week containing 4 January.
              SQL Server's DATEPART(week,...) does NOT follow ISO;
              DATEPART(ISO_WEEK,...) does, and is used throughout.

   STATUS   : Sections A-C are derived from verified ClinicMaster
              structures and lab test codes. Section D (notifiable
              disease case counts) is a skeleton: it needs the column
              names returned by 06_extract_schema_discovery.sql before
              the diagnosis-to-HMIS-code mapping can be completed.
              Nothing in Section D is emitted until that mapping is
              filled in, so running this today yields only the
              indicators that are known to be correct.
   ================================================================== */

SET NOCOUNT ON;

DECLARE @PeriodType char(1) = 'W';   -- 'W' = ISO week, 'M' = calendar month
DECLARE @Year       int      = 2026;
DECLARE @Period     int      = 35;   -- ISO week number, or month number

/* ---- Resolve the period to an inclusive date range ---------------- */
DECLARE @Start date, @End date;

IF @PeriodType = 'W'
BEGIN
    /* 4 January is always in ISO week 1. Step back to its Monday, then
       forward by the requested number of whole weeks. */
    DECLARE @Jan4 date = DATEFROMPARTS(@Year, 1, 4);
    DECLARE @Week1Mon date =
        DATEADD(day, -((DATEPART(weekday, @Jan4) + @@DATEFIRST - 2) % 7), @Jan4);
    SET @Start = DATEADD(week, @Period - 1, @Week1Mon);
    SET @End   = DATEADD(day, 6, @Start);
END
ELSE
BEGIN
    SET @Start = DATEFROMPARTS(@Year, @Period, 1);
    SET @End   = EOMONTH(@Start);
END

/* Reject an out-of-range week rather than silently reporting the wrong days. */
IF @PeriodType = 'W' AND DATEPART(ISO_WEEK, @Start) <> @Period
BEGIN
    RAISERROR('Week %d does not exist in ISO year %d.', 16, 1, @Period, @Year);
    RETURN;
END

DECLARE @EndX datetime = DATEADD(day, 1, CAST(@End AS datetime));  -- exclusive upper bound

/* Lab test codes confirmed present in ClinicMasterMOH.dbo.LabTests. */
DECLARE @MalariaRDT   varchar(20) = '407727009';   -- Malaria RDT
DECLARE @MalariaMicro varchar(20) = '372071003';   -- BS for mps (Malaria BS)
DECLARE @GeneXpert    varchar(20) = '9000001';     -- X-PERT MTB-Rif
DECLARE @MTBXDR       varchar(20) = 'LAB004';      -- MTB XDR

IF OBJECT_ID('tempdb..#tally') IS NOT NULL DROP TABLE #tally;
CREATE TABLE #tally (Code varchar(20) NOT NULL PRIMARY KEY, Value int NOT NULL);


/* ==================================================================
   SECTION A — OPD attendance and deaths  (033B codes AP01-AP03)
   ------------------------------------------------------------------
   AP02 is every visit in the period. AP01 is the subset whose visit
   category denotes a first presentation rather than a follow-up; the
   category values below mirror the mapping the compiler already uses
   for raw EMR exports (api/_lib/validators.py, _EMR_VISIT_TYPE).
   Confirm them against section 3 of the discovery script - if the
   category column holds identifiers rather than names, replace the
   IN-list with the corresponding identifiers.
   ================================================================== */

INSERT INTO #tally (Code, Value)
SELECT 'AP02', COUNT(*)
FROM   ClinicMasterMOH.dbo.Visits
WHERE  VisitDate >= @Start AND VisitDate < @EndX;

INSERT INTO #tally (Code, Value)
SELECT 'AP01', COUNT(*)
FROM   ClinicMasterMOH.dbo.Visits
WHERE  VisitDate >= @Start AND VisitDate < @EndX
  AND  ISNULL(VisitCategoryID, '') NOT IN
       ('Follow up', 'RTT - Return To Treatment', 'Represented', 'CDDP');


/* ==================================================================
   SECTION B — Malaria testing and treatment  (MA02-MA05)
   ------------------------------------------------------------------
   Counts of tests requested and of positive results, by the date the
   specimen was drawn. MA01 (suspected malaria) and MA06-MA10 (treated
   cases) depend on the diagnosis and prescription registers and are
   therefore deferred to Section D.
   ================================================================== */

INSERT INTO #tally (Code, Value)
SELECT 'MA02', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabRequestDetails d
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = d.SpecimenNo
WHERE  d.TestCode = @MalariaRDT
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX;

INSERT INTO #tally (Code, Value)
SELECT 'MA03', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabResults res
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = res.SpecimenNo
WHERE  res.TestCode = @MalariaRDT
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX
  AND  res.Result IS NOT NULL
  AND  UPPER(LTRIM(RTRIM(CAST(res.Result AS varchar(200)))))
       LIKE '%POSITIVE%';

INSERT INTO #tally (Code, Value)
SELECT 'MA04', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabRequestDetails d
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = d.SpecimenNo
WHERE  d.TestCode = @MalariaMicro
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX;

INSERT INTO #tally (Code, Value)
SELECT 'MA05', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabResults res
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = res.SpecimenNo
WHERE  res.TestCode = @MalariaMicro
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX
  AND  res.Result IS NOT NULL
  AND  UPPER(LTRIM(RTRIM(CAST(res.Result AS varchar(200)))))
       NOT LIKE '%NO %'
  AND  UPPER(LTRIM(RTRIM(CAST(res.Result AS varchar(200)))))
       NOT LIKE '%NEGATIVE%'
  AND  UPPER(LTRIM(RTRIM(CAST(res.Result AS varchar(200)))))
       NOT LIKE '%NIL%';


/* ==================================================================
   SECTION C — GeneXpert  (GP01-GP05)
   ------------------------------------------------------------------
   GP06 (modules working) and GP07 (cartridges remaining) are physical
   observations of the machine and its store. No register holds them;
   they are keyed in.
   ================================================================== */

INSERT INTO #tally (Code, Value)
SELECT 'GP01', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabRequestDetails d
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = d.SpecimenNo
WHERE  d.TestCode IN (@GeneXpert, @MTBXDR)
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX;

INSERT INTO #tally (Code, Value)
SELECT 'GP02', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabRequestDetails d
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = d.SpecimenNo
WHERE  d.TestCode IN (@GeneXpert, @MTBXDR)
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX
  AND  ISNULL(d.RejectedID, '') <> '';

INSERT INTO #tally (Code, Value)
SELECT 'GP03', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabResults res
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = res.SpecimenNo
WHERE  res.TestCode IN (@GeneXpert, @MTBXDR)
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX
  AND  UPPER(CAST(res.Result AS varchar(200))) LIKE '%DETECT%'
  AND  UPPER(CAST(res.Result AS varchar(200))) NOT LIKE '%NOT DETECT%';

INSERT INTO #tally (Code, Value)
SELECT 'GP04', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabResultsEXT x
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = x.SpecimenNo
WHERE  x.TestCode = @GeneXpert
  AND  x.SubTestCode = 'tj6l4jhh'                 -- RIF Resistance
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX
  AND  UPPER(CAST(x.Result AS varchar(200))) LIKE '%DETECT%'
  AND  UPPER(CAST(x.Result AS varchar(200))) NOT LIKE '%NOT DETECT%';

INSERT INTO #tally (Code, Value)
SELECT 'GP05', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabResults res
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = res.SpecimenNo
WHERE  res.TestCode IN (@GeneXpert, @MTBXDR)
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX
  AND  (UPPER(CAST(res.Result AS varchar(200))) LIKE '%ERROR%'
     OR UPPER(CAST(res.Result AS varchar(200))) LIKE '%INVALID%'
     OR UPPER(CAST(res.Result AS varchar(200))) LIKE '%NO RESULT%');


/* ==================================================================
   SECTION D — Notifiable disease case and death counts
   ------------------------------------------------------------------
   PENDING. Requires the Diagnosis and Diseases column names from
   06_extract_schema_discovery.sql. Once known, populate #map below with
   one row per 033B code and the disease identifiers that feed it, then
   uncomment the INSERT that follows. The shape is deliberately a lookup
   table rather than a wall of UNIONs, so that adding a condition is a
   one-line change and the mapping can be reviewed by the QA team
   without reading SQL.

   IF OBJECT_ID('tempdb..#map') IS NOT NULL DROP TABLE #map;
   CREATE TABLE #map (Code varchar(20), DiseaseKey varchar(100));
   INSERT INTO #map (Code, DiseaseKey) VALUES
       ('CD01a', 'Malaria'),          -- confirmed malaria - cases
       ('CD02a', 'Dysentery'),
       ('CD03a', 'SARI'),
       ('CD13a', 'Typhoid Fever'),
       ('CD14a', 'Hepatitis B');
       -- ... one row per condition on the form

   INSERT INTO #tally (Code, Value)
   SELECT m.Code, COUNT(*)
   FROM   ClinicMasterMOH.dbo.Diagnosis dg
   JOIN   ClinicMasterMOH.dbo.Visits v  ON v.VisitNo = dg.VisitNo
   JOIN   ClinicMasterMOH.dbo.Diseases ds ON ds.<key> = dg.<key>
   JOIN   #map m ON ds.<name column> LIKE '%' + m.DiseaseKey + '%'
   WHERE  v.VisitDate >= @Start AND v.VisitDate < @EndX
   GROUP BY m.Code;
   ================================================================== */


/* ==================================================================
   OUTPUT — the compiler's import format
   ------------------------------------------------------------------
   Two columns exactly: Code, Value. Export as CSV and upload.
   Indicators absent from this result are simply not derivable from
   ClinicMaster; leave them blank in the template so DHIS2 records them
   as not reported, or key in the true figure where one exists.
   ================================================================== */

SELECT Code, Value
FROM   #tally
ORDER BY Code;

/* Period actually covered, for the audit trail. Confirm this matches
   the period selected in the compiler before uploading. */
SELECT CASE WHEN @PeriodType = 'W'
            THEN CONCAT(@Year, 'W', @Period)
            ELSE CONCAT(@Year, RIGHT('0' + CAST(@Period AS varchar(2)), 2))
       END                                   AS period,
       CONVERT(varchar(10), @Start, 23)      AS period_start,
       CONVERT(varchar(10), @End, 23)        AS period_end,
       DATEDIFF(day, @Start, @End) + 1       AS days_covered;

DROP TABLE #tally;
