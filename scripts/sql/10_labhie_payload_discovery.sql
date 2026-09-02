/* ==================================================================
   LAB HIE / CPHL ALIS — PAYLOAD DISCOVERY
   ------------------------------------------------------------------
   Server   : 172.20.0.230        Database: ClinicMasterMOH

   WHY THIS EXISTS
   The published ALIS guide is a user manual: no endpoints, no payload
   structure, session login only. But ClinicMaster is ALREADY exchanging
   messages with the lab HIE — the INT-prefixed tables hold 331,986
   integration responses — and INTLabRequestDetails.JsonMessage contains
   the actual JSON that crosses the wire. The specification we need is
   therefore already in the database, written by the integration itself.

   SAFETY — READ THIS BEFORE RUNNING
   Those JSON messages contain PATIENT DATA: names, numbers, dates of
   birth. This script therefore returns the KEY NAMES ONLY, never the
   values. It reads the structure and discards the content, so what
   comes back describes the payload without describing any person.

   Sections 1 and 2 use OPENJSON, which needs SQL Server 2016 or later.
   If they error with "OPENJSON is not recognised", send me the error
   and skip to sections 3 and 4, which work on any version.

   USAGE : Run the whole script. It returns ONE grid, small enough to
           paste. Nothing here is a patient record.
   ================================================================== */

SET NOCOUNT ON;

IF OBJECT_ID('tempdb..#hie') IS NOT NULL DROP TABLE #hie;
CREATE TABLE #hie (section varchar(40), item varchar(300), detail varchar(400), number varchar(40));

/* ---- 1. Top-level keys of the outbound request payload ------------ */
BEGIN TRY
    INSERT INTO #hie (section, item, detail, number)
    SELECT '1_request_keys', k.[key],
           CASE k.type WHEN 0 THEN 'null' WHEN 1 THEN 'string' WHEN 2 THEN 'number'
                       WHEN 3 THEN 'boolean' WHEN 4 THEN 'array' WHEN 5 THEN 'object'
                       ELSE CAST(k.type AS varchar(10)) END,
           CAST(COUNT(*) AS varchar(40))
    FROM   (SELECT TOP 2000 JsonMessage
            FROM   ClinicMasterMOH.dbo.INTLabRequestDetails
            WHERE  JsonMessage IS NOT NULL AND ISJSON(JsonMessage) = 1
            ORDER BY RecordDateTime DESC) d
    CROSS APPLY OPENJSON(d.JsonMessage) k
    GROUP BY k.[key], k.type;
END TRY
BEGIN CATCH
    INSERT INTO #hie VALUES ('1_request_keys', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 2. Keys one level down, for nested objects and arrays -------- */
BEGIN TRY
    INSERT INTO #hie (section, item, detail, number)
    SELECT DISTINCT TOP 200 '2_nested_keys', outerk.[key] + ' > ' + innerk.[key],
           CASE innerk.type WHEN 1 THEN 'string' WHEN 2 THEN 'number' WHEN 3 THEN 'boolean'
                            WHEN 4 THEN 'array'  WHEN 5 THEN 'object' ELSE 'null' END,
           ''
    FROM   (SELECT TOP 500 JsonMessage
            FROM   ClinicMasterMOH.dbo.INTLabRequestDetails
            WHERE  JsonMessage IS NOT NULL AND ISJSON(JsonMessage) = 1
            ORDER BY RecordDateTime DESC) d
    CROSS APPLY OPENJSON(d.JsonMessage) outerk
    CROSS APPLY OPENJSON(CASE WHEN outerk.type IN (4,5) THEN outerk.value ELSE '{}' END) innerk;
END TRY
BEGIN CATCH
    INSERT INTO #hie VALUES ('2_nested_keys', '(failed)', LEFT(ERROR_MESSAGE(), 380), '');
END CATCH;

/* ---- 3. Which agents are configured, and how busy ----------------- */
INSERT INTO #hie (section, item, detail, number)
SELECT '3_agents', CAST(ISNULL(AgentNo, '(null)') AS varchar(300)), '',
       CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabRequestDetails
GROUP BY AgentNo;

/* ---- 4. Sync state and the shape of the Message field -------------
   Message is the integration's own status text. Its DISTINCT values are
   status strings, not patient data, and they tell us what the endpoint
   returns on success and on failure.                                  */
INSERT INTO #hie (section, item, detail, number)
SELECT '4_sync_status', CAST(ISNULL(CAST(SyncStatus AS varchar(10)), '(null)') AS varchar(300)),
       '', CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabRequestDetails
GROUP BY SyncStatus;

INSERT INTO #hie (section, item, detail, number)
SELECT TOP 30 '5_messages', CAST(LEFT(ISNULL(Message, '(null)'), 280) AS varchar(300)),
       '', CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabRequestDetails
GROUP BY CAST(LEFT(ISNULL(Message, '(null)'), 280) AS varchar(300))
ORDER BY COUNT(*) DESC;

/* ---- 6. Payload size, so we know what we are dealing with --------- */
INSERT INTO #hie (section, item, detail, number)
SELECT '6_shape', 'JsonMessage length (min / avg / max)',
       CAST(MIN(LEN(JsonMessage)) AS varchar(20)) + ' / ' +
       CAST(AVG(LEN(JsonMessage)) AS varchar(20)) + ' / ' +
       CAST(MAX(LEN(JsonMessage)) AS varchar(20)),
       CAST(COUNT(*) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabRequestDetails
WHERE  JsonMessage IS NOT NULL;

INSERT INTO #hie (section, item, detail, number)
SELECT '6_shape', 'rows with valid JSON', '',
       CAST(SUM(CASE WHEN JsonMessage IS NOT NULL AND ISJSON(JsonMessage) = 1
                     THEN 1 ELSE 0 END) AS varchar(40))
FROM   ClinicMasterMOH.dbo.INTLabRequestDetails;

/* ---- 7. The response side ----------------------------------------- */
INSERT INTO #hie (section, item, detail, number)
SELECT '7_response_tables', t.name, '',
       CAST(ISNULL((SELECT SUM(p.rows) FROM ClinicMasterMOH.sys.partitions p
                    WHERE p.object_id = t.object_id AND p.index_id IN (0,1)), 0) AS varchar(40))
FROM   ClinicMasterMOH.sys.tables t
WHERE  t.name LIKE 'INT%';

INSERT INTO #hie (section, item, detail, number)
SELECT '8_response_columns', t.name,
       CAST(LEFT(STUFF((SELECT ', ' + c.name
                        FROM ClinicMasterMOH.sys.columns c
                        WHERE c.object_id = t.object_id
                        ORDER BY c.column_id
                        FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, ''), 380)
            AS varchar(400)), ''
FROM   ClinicMasterMOH.sys.tables t
WHERE  t.name IN ('INTTestCMIntegrationResponse', 'INTLabResults', 'INTLabResultsEXT',
                  'INTLabRequestDetails', 'INTHIELabRequestDetails', 'INTHIELabResults');

SELECT section, item, detail, number FROM #hie ORDER BY section, item;

DROP TABLE #hie;
