/* ==================================================================
   CLINICMASTER - DISEASE DICTIONARY EXPORT
   ------------------------------------------------------------------
   Server   : 172.20.0.230        Database: ClinicMasterMOH

   SAFETY   : Read-only, and reference data only. The Diseases table is
              a code list - it contains no patient, no visit and no
              clinical record. Nothing here touches a person.

   PURPOSE  : This is the key to mapping ClinicMaster's conditions onto
              the ~600 HMIS 105:01 data elements, and to settling
              whether ICD-11 codes are genuinely populated on this
              instance or only nominally present.

   USAGE    : Roughly 18,000 rows - too many to paste. Run it, then use
              the "Save as CSV" icon at the top right of the results
              grid and attach the file. Give it a name of your own, such
              as diseases.csv, rather than accepting the default
              Results.csv, which Azure Data Studio reuses.
   ================================================================== */

SET NOCOUNT ON;

SELECT *
FROM   ClinicMasterMOH.dbo.Diseases;


/* ------------------------------------------------------------------
   If the grid above is unwieldy, this smaller alternative gives me
   most of what I need: run it INSTEAD and paste the result. It reports
   how complete each column is and shows a handful of examples, without
   the eighteen thousand rows.

   Comment out the SELECT above and uncomment this block.
   ------------------------------------------------------------------

SELECT TOP 40 * FROM ClinicMasterMOH.dbo.Diseases ORDER BY 1;

   ------------------------------------------------------------------ */
