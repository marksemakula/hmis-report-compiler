# HMIS 105:01 OR01 and OR02: referrals to and from the OPD

The compiler has prepared the 105:01 since August 2026. Neither referral line is
a diagnosis, so no translation of a diagnosis could produce them, and both have
stood empty in eHMIS since April 2026. From November 2026 the extraction script
counts them directly from ClinicMaster, by the OPD age bands and sex, over the
same attendances as OA01 and OA02.

The rules, and what they cannot see, are set out in full in
`api/_lib/referrals.py`; this note records the evidence behind them.

## The rules

| Line | Counted when | Source in ClinicMaster |
|------|--------------|------------------------|
| OR01 Referrals to unit | the OPD visit was registered as a referral (visit category 10R, "Refferal"), unless the referrer is recorded as SELF | `Visits.VisitCategoryID`, `Visits.ReferredBy` |
| OR02 Referrals from unit | an external referral form was filed for the visit, or the clinician's or triage notes refer the client to a named facility outside JRRH | `ExternalReferrals`; `ClinicalFindings` (presenting complaint, provisional diagnosis, clinical notes, treatment plan) and `Triage.Notes` |

Each line counts an attendance once, however many forms or phrases it carries.
A referral to a specialist inside JRRH, whether through the `Referrals` table or
a note such as "refer to physiotherapy", keeps the client in the hospital and is
not counted.

For OR02's notes, a referral phrase ("refer to", "referred to", "referral to",
"for referral", "transfer to" and their common misspellings) must be followed,
within 60 characters, in the same note and before any "from", by an outside
destination: Mulago and the other national referral hospitals, the Uganda Cancer
and Heart Institutes, CORSU, the Kampala mission hospitals, or a "higher level"
of care. "Referred to JRRH from Kakira" is therefore read as a referral in, not
out.

## What ClinicMaster holds, January to October 2026

Profiled read-only on 3 November 2026, over the OPD attendances the extract
counts. eHMIS figures are the values Jinja reported, read the same day.

| Month | eHMIS OR01 | Registered as referral (10R) | of which SELF | eHMIS OR02 | Referral forms on OPD visits | Notes naming an outside facility |
|-------|-----------:|-----------------------------:|--------------:|-----------:|-----------------------------:|---------------------------------:|
| January 2026 | 180 | 19 | 3 | 6 | 1 | not profiled |
| February 2026 | 182 | 40 | 2 | 2 | 1 | not profiled |
| March 2026 | 206 | 29 | 0 | 3 | 0 | not profiled |
| April 2026 | empty | 35 | 1 | empty | 1 | not profiled |
| May 2026 | empty | 33 | 0 | empty | 0 | not profiled |
| June 2026 | empty | 20 | 1 | empty | 0 | 2 |
| July 2026 | empty | 51 | 1 | empty | 0 | 1 |
| August 2026 | empty | 38 | 0 | empty | 0 | 2 |
| September 2026 | empty | 38 | 0 | empty | 0 | 6 |
| October 2026 | empty | 59 | 3 | empty | 0 | 3 |

Three findings follow.

1. **Registration records about one referral in six.** The 180 to 206 reported
   for January to March came from the paper register; ClinicMaster's referral
   category held 88 visits across the same three months against 568 reported.
   `Visits.ReferredBy` is filled on every 10R visit and on no other, so the
   category and the field are a single signal.
2. **The referral-out form is barely used.** ExternalReferrals held at most four
   forms a month in 2026, almost all for casualty patients who were then
   admitted, and none for an OPD attendance from June to October.
3. **The notes carry what the form does not.** Clinicians write "refer to
   Mulago for ...", "referral to UCI", "refer to CORSU hand surgery". Most
   "refer to" notes, however, send the client to a clinic inside JRRH (ENT,
   physiotherapy, the physician, dental), which is why the destination test is
   needed.

## October 2026, run live

The generated October script, run in Azure Data Studio against
ClinicMasterMOH, returned **OR01 = 56** and **OR02 = 3** (no forms; three
attendances whose notes referred the client to Mulago or Kiruddu). Both agree
box for box with an independent record-level tally of the same rules, and OR01
equals the 56 October 10R visits with a named referrer found by the profile.

## What the figures cannot see

* OR01 counts only what registration recorded. While the referral category is
  used for about a sixth of referred clients, OR01 is a floor. The remedy is at
  the registration desk: register every referred client under the "Refferal"
  category and type the referring unit.
* OR02 reads the first occurrence of each phrase in each note. It misses an
  outside destination the list does not name, and a referral nobody wrote down;
  it can also count a past referral mentioned in passing.
* Both lines should be read against the OPD register's referral columns while
  the two sources disagree.

## Checking it again

`scripts/test_referrals.py` holds the rules to the 105:01 mapping and to the
wording found in JRRH's notes; `referrals.records_select()` gives the
record-level tally to compare a live run against.
