/* ==================================================================
   HMIS REPORT COMPILER - HOW A CommunityID BECOMES A NAME
   ------------------------------------------------------------------
   Server   : 172.20.0.230
   Database : ClinicMasterMOH

   WHY      : The front end prints community names - NALUFENYA OPD,
              CHRONIC CARE (SICKLE CELL), CCC NALUFENYA - but the
              database holds only codes, 507NAL and the like. There is
              no foreign key on CommunityID and no table anywhere
              carries a community name, so the resolution happens
              inside a view or a procedure. Twenty-four objects mention
              the column; two of them are the ones that matter.

              uspGetVisits reads visits, and CancerAndNormalDiagnosis
              is a diagnosis view, so the "Diagnosis OPD" table the
              front end shows is almost certainly one of them. Their
              text will name the table the community name comes from,
              and that is the last thing needed before the rule "an
              OPD client is one whose community is not a ward" can be
              written into the extract.

   HOW      : Rather than return two procedures in full, this returns a
              400-character window around each of the first twelve
              mentions of Community in each. That is enough to read the
              JOIN and short enough to paste back.

   SAFETY   : Read-only, and it reads only the text of the database's
              own code. No table of data is touched at all, so no
              patient row, name, number or village is read.

   OUTPUT   : ONE grid, at most 24 rows. Widen column C to read it, or
              export to CSV.
   ================================================================== */

SET NOCOUNT ON;

WITH src AS (
    SELECT   o.name COLLATE DATABASE_DEFAULT       AS obj,
             m.definition COLLATE DATABASE_DEFAULT AS body
    FROM     ClinicMasterMOH.sys.sql_modules m
    JOIN     ClinicMasterMOH.sys.objects     o ON o.object_id = m.object_id
    WHERE    o.name IN ('uspGetVisits', 'CancerAndNormalDiagnosis')
),
/* Each mention of the word in turn. CHARINDEX finds the first; the
   recursive step starts the next search one character further on. */
hit AS (
    SELECT   obj, CHARINDEX('Community', body) AS pos, 1 AS k
    FROM     src
    WHERE    CHARINDEX('Community', body) > 0
    UNION ALL
    SELECT   h.obj, CHARINDEX('Community', s.body, h.pos + 1), h.k + 1
    FROM     hit h
    JOIN     src s ON s.obj = h.obj
    WHERE    CHARINDEX('Community', s.body, h.pos + 1) > 0
      AND    h.k < 12
)
SELECT   '1_community_join'                                    AS section,
         h.obj                                                 AS a,
         CAST(h.k AS varchar(4)) + ' @ ' + CAST(h.pos AS varchar(12)) AS b,
         REPLACE(REPLACE(
             SUBSTRING(s.body,
                       CASE WHEN h.pos > 200 THEN h.pos - 200 ELSE 1 END,
                       400),
             CHAR(13), ' '), CHAR(10), ' ')                    AS c
FROM     hit h
JOIN     src s ON s.obj = h.obj
ORDER BY a, h.k
OPTION   (MAXRECURSION 100);
