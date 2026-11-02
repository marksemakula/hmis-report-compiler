/* ==================================================================
   HMIS REPORT COMPILER - CASUALTY TRANSFERS AND DEATHS   [v1]
   ------------------------------------------------------------------
   Server   : 172.20.0.230
   Database : ClinicMasterMOH

   Read-only. What WardTransfer holds for casualty admissions, and
   when casualty clients' deaths fall relative to arrival and to the
   first transfer, for the ES09 line of the 105:01 emergency section
   (api/_lib/emergency.py).

   On 2 November 2026 it showed that the first WardTransfer row of
   every admission is the admission's own placement (from and to the
   same ward), so "never transferred" cannot mean "still in casualty";
   and that every death register entry is dated at midnight, so the
   death window is the arrival day and the next.

   Counts only; no patient row is returned. Change the two dates to
   measure another period.
   ================================================================== */

WITH used AS (
    SELECT DISTINCT vv.CommunityID FROM ClinicMasterMOH.dbo.Visits vv
    WHERE vv.VisitDate >= '2026-06-01' AND vv.VisitDate < '2026-11-01'
), comm AS (
    SELECT u.CommunityID, ISNULL(ClinicMasterMOH.dbo.GetLookupDataDes(u.CommunityID), '') AS name FROM used u
), ae AS (
    SELECT  vv.VisitNo, vv.PatientNo, vv.VisitDate, CONVERT(varchar(7), vv.VisitDate, 120) AS m
    FROM    ClinicMasterMOH.dbo.Visits vv
    JOIN    comm ON comm.CommunityID = vv.CommunityID
    WHERE   vv.VisitDate >= '2026-06-01' AND vv.VisitDate < '2026-11-01'
      AND   LTRIM(RTRIM(ISNULL(comm.name, ''))) IN ('ACCIDENT AND EMERGENCY')
), eadm AS (
    SELECT  a.VisitNo, a.AdmissionNo, a.AdmissionDateTime, r.WardsID,
            ROW_NUMBER() OVER (PARTITION BY a.VisitNo ORDER BY a.AdmissionDateTime, a.AdmissionNo) AS k
    FROM    ClinicMasterMOH.dbo.Admissions a
    JOIN    ae ON ae.VisitNo = a.VisitNo
    LEFT JOIN ClinicMasterMOH.dbo.Beds b  ON b.BedNo  = a.BedNo
    LEFT JOIN ClinicMasterMOH.dbo.Rooms r ON r.RoomNo = b.RoomNo
), wt1 AS (
    SELECT  wt.AdmissionNo, wt.TransferDate, wt.TransferFromWard, wt.TransferToWard,
            ROW_NUMBER() OVER (PARTITION BY wt.AdmissionNo ORDER BY wt.TransferDate, wt.TransferID) AS k
    FROM    ClinicMasterMOH.dbo.WardTransfer wt
    JOIN    eadm m ON m.AdmissionNo = wt.AdmissionNo AND m.k = 1
), base AS (
    SELECT  ae.m, ae.VisitNo, ae.PatientNo, ae.VisitDate, m.AdmissionNo, m.AdmissionDateTime, m.WardsID,
            t.TransferDate, t.TransferFromWard, t.TransferToWard,
            dr.DeathDate, dr.TimeOfDeath, ds.DischargeDateTime AS DeceasedAt
    FROM    ae
    LEFT JOIN eadm m ON m.VisitNo = ae.VisitNo AND m.k = 1
    LEFT JOIN wt1 t ON t.AdmissionNo = m.AdmissionNo AND t.k = 1
    OUTER APPLY (SELECT TOP 1 d.DeathDate, d.TimeOfDeath FROM ClinicMasterMOH.dbo.Deaths d
                 WHERE d.PatientNo = ae.PatientNo AND d.DeathDate >= CAST(ae.VisitDate AS date)
                   AND d.DeathDate < DATEADD(day, 8, CAST(ae.VisitDate AS date)) ORDER BY d.DeathDate) dr
    OUTER APPLY (SELECT TOP 1 x.DischargeDateTime FROM ClinicMasterMOH.dbo.Discharges x
                 WHERE x.AdmissionNo = m.AdmissionNo AND x.DischargeStatusID = '35D') ds
)
SELECT 'TRFROM' AS Q, CAST(ISNULL(TransferFromWard, '(none)') AS nvarchar(100)) AS A,
       CAST(ISNULL(ClinicMasterMOH.dbo.GetLookupDataDes(TransferFromWard), '') AS nvarchar(100)) AS B,
       CAST(CASE WHEN WardsID = TransferFromWard THEN 'from = bed ward' WHEN TransferFromWard IS NULL THEN '' ELSE 'from <> bed ward' END AS nvarchar(100)) AS C,
       COUNT(*) AS N
FROM base WHERE AdmissionNo IS NOT NULL
GROUP BY TransferFromWard, CASE WHEN WardsID = TransferFromWard THEN 'from = bed ward' WHEN TransferFromWard IS NULL THEN '' ELSE 'from <> bed ward' END
UNION ALL
SELECT 'TRTO', CAST(ISNULL(TransferToWard, '(none)') AS nvarchar(100)),
       CAST(ISNULL(ClinicMasterMOH.dbo.GetLookupDataDes(TransferToWard), '') AS nvarchar(100)), '', COUNT(*)
FROM base WHERE AdmissionNo IS NOT NULL GROUP BY TransferToWard
UNION ALL
SELECT 'TRLAG', m,
       CAST(CASE WHEN TransferDate IS NULL THEN 'no transfer'
                 WHEN DATEDIFF(minute, AdmissionDateTime, TransferDate) < 0 THEN 'before admission'
                 WHEN DATEDIFF(minute, AdmissionDateTime, TransferDate) < 60 THEN '<1h'
                 WHEN DATEDIFF(minute, AdmissionDateTime, TransferDate) < 360 THEN '1-6h'
                 WHEN DATEDIFF(minute, AdmissionDateTime, TransferDate) < 1440 THEN '6-24h'
                 ELSE '24h+' END AS nvarchar(100)), '', COUNT(*)
FROM base WHERE AdmissionNo IS NOT NULL
GROUP BY m, CASE WHEN TransferDate IS NULL THEN 'no transfer'
                 WHEN DATEDIFF(minute, AdmissionDateTime, TransferDate) < 0 THEN 'before admission'
                 WHEN DATEDIFF(minute, AdmissionDateTime, TransferDate) < 60 THEN '<1h'
                 WHEN DATEDIFF(minute, AdmissionDateTime, TransferDate) < 360 THEN '1-6h'
                 WHEN DATEDIFF(minute, AdmissionDateTime, TransferDate) < 1440 THEN '6-24h'
                 ELSE '24h+' END
UNION ALL
SELECT 'DEATH', m,
       CAST(CASE WHEN AdmissionNo IS NULL THEN 'not admitted'
                 WHEN TransferDate IS NULL THEN 'admitted, never transferred'
                 WHEN COALESCE(DeceasedAt, DeathDate) <= TransferDate THEN 'died by first transfer'
                 ELSE 'died after first transfer' END AS nvarchar(100)),
       CAST(CASE WHEN DATEDIFF(hour, VisitDate, COALESCE(DeceasedAt, DeathDate)) < 24 THEN '<24h of visit'
                 WHEN DATEDIFF(hour, VisitDate, COALESCE(DeceasedAt, DeathDate)) < 48 THEN '24-48h'
                 ELSE '48h+' END
            + CASE WHEN DeathDate IS NOT NULL AND DeceasedAt IS NOT NULL THEN ' | both'
                   WHEN DeathDate IS NOT NULL THEN ' | register only' ELSE ' | discharge only' END
            + ' | bed ' + ISNULL(WardsID, '-') + ' | to ' + ISNULL(TransferToWard, '-') AS nvarchar(100)),
       COUNT(*)
FROM base WHERE DeathDate IS NOT NULL OR DeceasedAt IS NOT NULL
GROUP BY m,
       CASE WHEN AdmissionNo IS NULL THEN 'not admitted'
                 WHEN TransferDate IS NULL THEN 'admitted, never transferred'
                 WHEN COALESCE(DeceasedAt, DeathDate) <= TransferDate THEN 'died by first transfer'
                 ELSE 'died after first transfer' END,
       CASE WHEN DATEDIFF(hour, VisitDate, COALESCE(DeceasedAt, DeathDate)) < 24 THEN '<24h of visit'
                 WHEN DATEDIFF(hour, VisitDate, COALESCE(DeceasedAt, DeathDate)) < 48 THEN '24-48h'
                 ELSE '48h+' END
            + CASE WHEN DeathDate IS NOT NULL AND DeceasedAt IS NOT NULL THEN ' | both'
                   WHEN DeathDate IS NOT NULL THEN ' | register only' ELSE ' | discharge only' END
            + ' | bed ' + ISNULL(WardsID, '-') + ' | to ' + ISNULL(TransferToWard, '-')
UNION ALL
SELECT 'DTIME', CAST(COUNT(*) AS varchar(10)),
       CAST(SUM(CASE WHEN CAST(DeathDate AS time) = '00:00' THEN 1 ELSE 0 END) AS nvarchar(100)) + ' at midnight',
       CAST(SUM(CASE WHEN ISNULL(TimeOfDeath, '') <> '' THEN 1 ELSE 0 END) AS nvarchar(100)) + ' with TimeOfDeath', 0
FROM ClinicMasterMOH.dbo.Deaths WHERE DeathDate >= '2026-06-01'
ORDER BY Q, A, N DESC;
