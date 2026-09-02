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
   AP02 is every visit in the period. AP01 is new attendances.

   CORRECTED 2 September 2026. AP01 previously excluded visits whose
   VisitCategoryID was 'Follow up', 'RTT - Return To Treatment',
   'Represented' or 'CDDP'. That column holds CODES, not names —
   10C, 10CDDP, 10O, 10R, 10RP, 10RTT, 10S — so the exclusion matched
   nothing and AP01 came back identical to AP02. Week 35 of 2026
   reported 3,619 for both.

   It is now computed the way the Ministry defines it and the way the
   OPD extract already did: a patient's FIRST visit within the
   reporting period is new, and any later visit in the same period is
   a re-attendance. That is a property of the period, not of a
   category anyone ticked.
   ================================================================== */

INSERT INTO #tally (Code, Value)
SELECT 'AP02', COUNT(*)
FROM   ClinicMasterMOH.dbo.Visits
WHERE  VisitDate >= @Start AND VisitDate < @EndX;

INSERT INTO #tally (Code, Value)
SELECT 'AP01', COUNT(*)
FROM   (SELECT ROW_NUMBER() OVER (PARTITION BY PatientNo
                                  ORDER BY VisitDate, VisitNo) AS seq_in_period
        FROM   ClinicMasterMOH.dbo.Visits
        WHERE  VisitDate >= @Start AND VisitDate < @EndX) v
WHERE  v.seq_in_period = 1;


/* ==================================================================
   CLASSIFYING A LABORATORY RESULT
   ------------------------------------------------------------------
   ADDED 2 September 2026, because four tallies below were wrong.

   Every result tally previously read LabResults.Result. That column is
   blank in 25,915 of its 28,252 rows: the parent is a container, and
   the value lives one level down in LabResultsEXT, one row per
   analyte. MA03 and GP03 therefore returned zero for week 35 while
   real positives existed, and MA05 counted blanks as positive smears
   because '' is not NULL and passes every NOT LIKE exclusion.

   Two ordering rules are built into the CASE and neither is optional:

     NON REACTIVE contains REACTIVE, so negatives are tested first.
     'MTB DETECTED MEDIUM,RIF resistance NOT DETECTED' contains NOT
     DETECTED, so only the clause before the first comma is read. The
     old GP03 excluded anything matching '%NOT DETECT%' and so threw
     away every Xpert positive it had just found.

   POSTIVE is not a typing slip. It is the spelling held in
   LabPossibleResults, the list the laboratory picks from, for HIV
   serology, HBsAg, TPHA, HCG-BETA and malaria RDT. It must be
   accepted, and it should be corrected in ClinicMaster.
   ================================================================== */

IF OBJECT_ID('tempdb..#res') IS NOT NULL DROP TABLE #res;
CREATE TABLE #res (SpecimenNo varchar(50), TestCode varchar(30),
                   SubTestCode varchar(50), Verdict varchar(12));

INSERT INTO #res (SpecimenNo, TestCode, SubTestCode, Verdict)
SELECT x.SpecimenNo, x.TestCode, x.SubTestCode,
       CASE
         WHEN c.lead LIKE '%INVALID%'                                THEN 'Invalid'
         WHEN c.lead LIKE '%NON REACTIVE%' OR c.lead LIKE '%NOT DETECT%'
           OR c.lead LIKE '%NO MPS%'       OR c.lead LIKE '%NO PLASMODIUM%'
           OR c.lead LIKE '%NEGATIVE%'     OR c.lead LIKE '%NEGAITVE%'
           OR c.lead LIKE '%NOT SEEN%'                               THEN 'Negative'
         WHEN c.lead LIKE '%DETECT%'       OR c.lead LIKE '%REACTIVE%'
           OR c.lead LIKE '%POSITIVE%'     OR c.lead LIKE '%POSTIVE%'
           OR c.lead LIKE '%POSITVE%'      OR c.lead LIKE '%MPS%SEEN%' THEN 'Positive'
         ELSE NULL END
FROM   ClinicMasterMOH.dbo.LabResultsEXT x
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = x.SpecimenNo
CROSS APPLY (SELECT UPPER(REPLACE(
                LEFT(CAST(ISNULL(x.Result, '') AS varchar(200)),
                     CHARINDEX(',', CAST(ISNULL(x.Result, '') AS varchar(200)) + ',') - 1),
                '-', ' ')) AS lead) c
WHERE  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX;


/* ==================================================================
   SECTION B — Malaria testing and treatment  (MA02-MA05)
   ------------------------------------------------------------------
   Counts of tests requested and of positive results, by the date the
   specimen was drawn. MA01 (suspected malaria) and MA06-MA10 (treated
   cases) depend on the diagnosis and prescription registers and are
   therefore deferred to Section D.

   The reportable analyte differs by test: malaria RDT reports under a
   sub-test code equal to its own test code, while microscopy reports
   under '01' (Detection). Species, Stage and Parasite Density are
   separate analytes of the same smear and must not be counted again.
   ================================================================== */

/* MA02 — "Cases Tested with RDT", in the Ministry's own words on the
   033B form. TESTED, not requested.

   CORRECTED 3 September 2026. This counted rows in LabRequestDetails,
   which is the order, not the test. Week 35 showed why that matters:
   173 RDTs were ordered and not one result was ever recorded — the
   diagnostic returned zero rows in LabResultsEXT, not zero positives.
   Reporting "173 tested, 0 positive" would have told the Ministry that
   Jinja found no positive rapid test all week. Reporting "0 tested,
   0 positive" says the true thing, which is that the lab module holds
   no RDT results at all.

   The order counts remain in the grid as _req_* rows, because the gap
   between ordered and resulted is itself worth watching. */
INSERT INTO #tally (Code, Value)
SELECT 'MA02', COUNT(*)
FROM   #res
WHERE  TestCode = @MalariaRDT AND SubTestCode = @MalariaRDT
  AND  Verdict IS NOT NULL;

INSERT INTO #tally (Code, Value)
SELECT '_req_rdt', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabRequestDetails d
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = d.SpecimenNo
WHERE  d.TestCode = @MalariaRDT
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX;

INSERT INTO #tally (Code, Value)
SELECT 'MA03', COUNT(*)
FROM   #res
WHERE  TestCode = @MalariaRDT AND SubTestCode = @MalariaRDT
  AND  Verdict = 'Positive';

/* MA04 — "Cases Tested with Microscopy". Same correction: 199 smears
   were ordered in week 35 and 88 carry a readable Detection result.
   Counting the 199 understated positivity from 20 per cent to 9. */
INSERT INTO #tally (Code, Value)
SELECT 'MA04', COUNT(*)
FROM   #res
WHERE  TestCode = @MalariaMicro AND SubTestCode = '01'
  AND  Verdict IS NOT NULL;

INSERT INTO #tally (Code, Value)
SELECT '_req_smear', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabRequestDetails d
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = d.SpecimenNo
WHERE  d.TestCode = @MalariaMicro
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX;

/* Microscopy positives read the Detection analyte only. A graded smear
   — MPS +, ++ or +++ SEEN — is a positive; NO MPS SEEN and
   'No Plasmodium Parasites' are not. The previous version counted a
   smear as positive whenever the parent Result was merely non-NULL,
   which a blank string satisfies. */
INSERT INTO #tally (Code, Value)
SELECT 'MA05', COUNT(*)
FROM   #res
WHERE  TestCode = @MalariaMicro AND SubTestCode = '01'
  AND  Verdict = 'Positive';


/* ==================================================================
   SECTION C — GeneXpert  (GP01-GP05)
   ------------------------------------------------------------------
   GP06 (modules working) and GP07 (cartridges remaining) are physical
   observations of the machine and its store. No register holds them;
   they are keyed in.
   ================================================================== */

/* GP01 — "No. of samples tested". Week 35 ordered 21 and resulted 6,
   so GP03's single MTB detection is one of six, not one of twenty-one. */
INSERT INTO #tally (Code, Value)
SELECT 'GP01', COUNT(*)
FROM   #res
WHERE  TestCode IN (@GeneXpert, @MTBXDR) AND SubTestCode = 'ma7dy01a'
  AND  Verdict IS NOT NULL;

INSERT INTO #tally (Code, Value)
SELECT '_req_xpert', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabRequestDetails d
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = d.SpecimenNo
WHERE  d.TestCode IN (@GeneXpert, @MTBXDR)
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX;

/* GP02 — specimens rejected.

   This once counted rows where RejectedID was non-blank and returned
   21 against GP01's 21, reporting every GeneXpert specimen as
   rejected. The diagnostic added on 2 September settled why: across
   all 2,319 lab request details in week 35 the column held exactly one
   value, '54N'. It is a coded column like the rest of this schema —
   GenderID is 15F/15M, VisitStatusID is 9CO/9DR/9IP — and 54N is the
   "not rejected" code, never an empty string.

   Rejected is therefore anything that is not 54N. An unfamiliar code
   counts as rejected rather than being quietly ignored, because a
   rejection tally is a quality signal: over-reporting prompts someone
   to look, under-reporting hides the problem. The _rejectedid_ rows
   below stay in the output permanently so a new code announces itself
   instead of being absorbed. */
INSERT INTO #tally (Code, Value)
SELECT 'GP02', COUNT(*)
FROM   ClinicMasterMOH.dbo.LabRequestDetails d
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = d.SpecimenNo
WHERE  d.TestCode IN (@GeneXpert, @MTBXDR)
  AND  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX
  AND  ISNULL(LTRIM(RTRIM(d.RejectedID)), '') NOT IN ('54N', '');

INSERT INTO #tally (Code, Value)
SELECT LEFT('_rejectedid_' + ISNULL(NULLIF(LTRIM(RTRIM(d.RejectedID)), ''), 'blank'), 20),
       COUNT(*)
FROM   ClinicMasterMOH.dbo.LabRequestDetails d
JOIN   ClinicMasterMOH.dbo.LabRequests r ON r.SpecimenNo = d.SpecimenNo
WHERE  r.DrawnDateTime >= @Start AND r.DrawnDateTime < @EndX
GROUP BY LEFT('_rejectedid_' + ISNULL(NULLIF(LTRIM(RTRIM(d.RejectedID)), ''), 'blank'), 20);

/* GP03 — TB detected. Reads the MTB analyte, and reads only the clause
   before the first comma, because a positive Xpert result reads
   'MTB DETECTED MEDIUM,RIF resistance NOT DETECTED' and the previous
   NOT LIKE '%NOT DETECT%' threw exactly those away. */
INSERT INTO #tally (Code, Value)
SELECT 'GP03', COUNT(*)
FROM   #res
WHERE  TestCode IN (@GeneXpert, @MTBXDR)
  AND  SubTestCode = 'ma7dy01a'
  AND  Verdict = 'Positive';

INSERT INTO #tally (Code, Value)
/* GP04 — rifampicin resistance. This one already read the right table,
   and its RIF Resistance analyte carries a standalone value with no
   second clause, so the leading-clause rule changes nothing here. It
   goes through #res for consistency, and so that a future change to
   the vocabulary reaches every tally at once. */
SELECT 'GP04', COUNT(*)
FROM   #res
WHERE  TestCode = @GeneXpert
  AND  SubTestCode = 'tj6l4jhh'                   -- RIF Resistance
  AND  Verdict = 'Positive';

INSERT INTO #tally (Code, Value)
SELECT 'GP05', COUNT(*)
FROM   #res
WHERE  TestCode IN (@GeneXpert, @MTBXDR)
  AND  SubTestCode = 'ma7dy01a'
  AND  Verdict = 'Invalid';


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

/* The _req_* rows above carry the ORDER counts that MA02, MA04 and
   GP01 used to report. Keeping them in the grid makes the gap between
   ordered and resulted visible every week rather than only when
   somebody goes looking:

       week 35, 2026 — RDT 173 ordered, 0 resulted
                       smear 199 ordered, 88 resulted
                       Xpert 21 ordered, 6 resulted

   A widening gap is a laboratory workflow problem, not a reporting
   one, and the form cannot show it. This grid can.
   ================================================================== */


/* Period actually covered, carried in the same grid as the tally.
   It used to be a second SELECT, which meant Azure Data Studio — which
   saves one grid per CSV — discarded it every time. Confirm these rows
   match the period selected in the compiler before uploading.

   The leading underscore sorts them above the codes and marks them as
   metadata rather than a tally the compiler should read. */
INSERT INTO #tally (Code, Value) VALUES
    ('_days_covered', DATEDIFF(day, @Start, @End) + 1),
    ('_start_yyyymmdd', CAST(CONVERT(varchar(8), @Start, 112) AS int)),
    ('_end_yyyymmdd',   CAST(CONVERT(varchar(8), @End,   112) AS int)),
    ('_period_year',    @Year),
    ('_period_number',  @Period);

SELECT Code, Value
FROM   #tally
ORDER BY Code;

DROP TABLE #tally;
IF OBJECT_ID('tempdb..#res') IS NOT NULL DROP TABLE #res;
