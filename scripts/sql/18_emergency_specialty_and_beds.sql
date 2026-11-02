/* ==================================================================
   HMIS REPORT COMPILER - CASUALTY VISITS BY SPECIALTY AND BED   [v1]
   ------------------------------------------------------------------
   Server   : 172.20.0.230
   Database : ClinicMasterMOH

   Read-only. Measures part of the ground the 105:01 emergency section
   (ES01, ES07, ES08, ES09; api/_lib/emergency.py) stands on: casualty
   visits by month and treating specialty, by the ward of the bed
   booked at admission, and the columns of WardTransfer.

   On 2 November 2026 this showed the September change. Visits moved
   from GENERAL DOCTOR to PHYSICIAN and SURGEON, and admissions moved
   off casualty's own ward (40440) onto destination wards, including
   146 onto the eye wards in September and 257 onto the TB ward in
   October. That is why eye-ward beds are not read as surgical.

   Counts and column names only; no patient row is returned. Change
   the two dates to measure another period. Script 19 follows on.
   ================================================================== */

WITH used AS (
    SELECT DISTINCT vv.CommunityID FROM ClinicMasterMOH.dbo.Visits vv
    WHERE vv.VisitDate >= '2026-06-01' AND vv.VisitDate < '2026-11-01'
), comm AS (
    SELECT u.CommunityID, ISNULL(ClinicMasterMOH.dbo.GetLookupDataDes(u.CommunityID), '') AS name FROM used u
), ae AS (
    SELECT  vv.VisitNo, vv.VisitDate, vv.DoctorSpecialtyID, CONVERT(varchar(7), vv.VisitDate, 120) AS m
    FROM    ClinicMasterMOH.dbo.Visits vv
    JOIN    comm ON comm.CommunityID = vv.CommunityID
    WHERE   vv.VisitDate >= '2026-06-01' AND vv.VisitDate < '2026-11-01'
      AND   LTRIM(RTRIM(ISNULL(comm.name, ''))) IN ('ACCIDENT AND EMERGENCY')
), eadm AS (
    SELECT  a.VisitNo, a.AdmissionNo, r.WardsID,
            ROW_NUMBER() OVER (PARTITION BY a.VisitNo ORDER BY a.AdmissionDateTime, a.AdmissionNo) AS k
    FROM    ClinicMasterMOH.dbo.Admissions a
    JOIN    ae ON ae.VisitNo = a.VisitNo
    LEFT JOIN ClinicMasterMOH.dbo.Beds b  ON b.BedNo  = a.BedNo
    LEFT JOIN ClinicMasterMOH.dbo.Rooms r ON r.RoomNo = b.RoomNo
)
SELECT 'SPEC' AS Q, ae.m AS A, CAST(ISNULL(ae.DoctorSpecialtyID, '(none)') AS nvarchar(200)) AS B,
       CAST(ISNULL(ClinicMasterMOH.dbo.GetLookupDataDes(ae.DoctorSpecialtyID), '') AS nvarchar(200)) AS C, COUNT(*) AS N
FROM ae GROUP BY ae.m, ae.DoctorSpecialtyID
UNION ALL
SELECT 'BEDWARD', ae.m, CAST(ISNULL(m.WardsID, '(not admitted)') AS nvarchar(200)),
       CAST(ISNULL(ClinicMasterMOH.dbo.GetLookupDataDes(m.WardsID), '') AS nvarchar(200)), COUNT(*)
FROM ae LEFT JOIN eadm m ON m.VisitNo = ae.VisitNo AND m.k = 1
GROUP BY ae.m, m.WardsID
UNION ALL
SELECT 'WTCOL', CAST(c.column_id AS varchar(7)), CAST(c.name AS nvarchar(200)), CAST(t.name AS nvarchar(200)), CAST(c.max_length AS int)
FROM sys.columns c JOIN sys.types t ON t.user_type_id = c.user_type_id
WHERE c.object_id = OBJECT_ID('ClinicMasterMOH.dbo.WardTransfer')
UNION ALL
SELECT 'WTROWS', CONVERT(varchar(7), MIN(a.AdmissionDateTime), 120), CAST(COUNT(DISTINCT wt.AdmissionNo) AS nvarchar(200)), '', COUNT(*)
FROM ClinicMasterMOH.dbo.WardTransfer wt JOIN ClinicMasterMOH.dbo.Admissions a ON a.AdmissionNo = wt.AdmissionNo
WHERE a.AdmissionDateTime >= '2026-06-01'
ORDER BY Q, A, N DESC;
