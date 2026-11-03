"""HMIS 105:01 OR01 and OR02, referrals into and out of the OPD, from ClinicMaster.

WHAT THE FORM ASKS FOR

    OR01  Referrals to unit     clients who came to the OPD on a referral
    OR02  Referrals from unit   clients the OPD referred on to another facility

both by the OPD age bands and sex, so both are counted over the OPD attendances
themselves - the same visits, banded the same way, as OA01 and OA02.

WHAT JINJA HAS REPORTED (eHMIS data values, read 3 November 2026)

    OR01  14 and 20 in July and August 2024; 13 and 13 in November and December
          2025; 180, 182 and 206 in January to March 2026; nothing since.
    OR02  1 in July 2024; 6, 2 and 3 in January to March 2026; nothing since.

From August 2026 the compiler has prepared the 105:01, and neither line is a
diagnosis, so the extract never produced them and they stood empty.

WHAT CLINICMASTER HOLDS (profiled read-only on 3 November 2026, OPD attendances)

  * Registration has a visit category. 10R, which the lookup spells "Refferal",
    is the only one that means a referral in: 10RP is "Represented", 10RTT is
    "RTT - Return To Treatment", 10S is "Self Request". Visits.ReferredBy is
    filled on every 10R visit and on no other, so the category and the field
    are one signal, not two. A few 10R visits name the referrer as SELF.
  * 10R visits numbered 19, 40, 29, 35, 33, 20, 51, 38, 38 and 59 in January to
    October 2026. The 180 to 206 reported for January to March therefore came
    from the paper register, not from this field; registration records roughly
    one referral in six.
  * ExternalReferrals, the referral-out form, held at most four forms a month
    in 2026, almost all for casualty patients who were then admitted; only
    three belonged to an OPD attendance, and none from June to October.
  * Clinicians do write the referral in the notes: "refer to Mulago for ...",
    "referral to UCI", "refer to CORSU hand surgery" - 2, 1, 2, 6 and 3 such
    attendances in June to October. Most "refer to" notes, though, send the
    client to a clinic inside JRRH (ENT, physiotherapy, the physician, dental),
    which is not a referral from the unit to another facility.

THE RULES

OR01.   An OPD attendance registered as a referral: visit category 10R, unless
        the referrer is recorded as SELF. One per visit.

OR02.   An OPD attendance with an external referral form against it, or whose
        clinical or triage notes say the client was referred to a facility
        outside JRRH: a referral phrase ("refer to", "referred to", "referral
        to", "for referral", "transfer to" and common misspellings) followed,
        in the same note, before any "from" and within WINDOW characters, by
        a named outside destination - the national referral and specialised
        hospitals, the Kampala mission hospitals, or a "higher level" of care.
        One per visit, however many forms or phrases.

        A referral to a specialist inside JRRH (the Referrals table, or a note
        such as "refer to physiotherapy") keeps the client in the hospital and
        is not counted.

WHAT THIS CANNOT SEE

OR01 counts only what registration recorded, which has been about a sixth of
the register's figure; it is a floor, and the fix is at the registration desk
(the "Refferal" category with the referring unit named). OR02 reads only the
first time each phrase occurs in each note, and misses an outside destination
the list does not name or a note nobody wrote; it can also count a past
referral the clinician mentions in passing. Both lines should be read
against the OPD register's referral columns while the two disagree.
"""
from .emergency import like_any

# Visit categories that mean the client arrived on a referral. GetLookupDataDes
# returns "Refferal" for 10R; "Represented" (10RP), "RTT - Return To Treatment"
# (10RTT) and "Self Request" (10S) are not referrals and are deliberately absent.
REFERRAL_IN_CATEGORIES = ("10R",)

# A 10R visit whose referrer is typed as this came on its own, not on a referral.
SELF_REFERRER = "SELF"

# Phrases that introduce a referral out. Each is looked for once per note.
OUT_PHRASES = (
    "REFER TO", "REFFER TO", "REFERRED TO", "REFERED TO", "REFFERED TO",
    "REFERRAL TO", "REFERAL TO", "REFFERAL TO", "REF TO", "REFERRED OUT",
    "FOR REFERRAL", "TRANSFER TO", "TRANSFERRED TO",
)

# Places outside JRRH a Jinja OPD client is referred on to. A leading space
# keeps a short name from matching inside a longer word.
DESTINATIONS = (
    "MULAGO", "MNRH", "MNHR", " NRH", "NATIONAL REFERRAL",
    "KIRUDDU", "KIRUDU", "KAWEMPE", "BUTABIKA",
    " UCI", "CANCER INST", " UHI", "HEART INST", "CORSU",
    "NSAMBYA", "LUBAGA", "RUBAGA", "MENGO", "KAMPALA",
    "HIGHER LEVEL", "HIGHER CENT", "HIGHER FACILITY", "TERTIARY", "ABROAD",
)

# How far after the phrase the destination may sit. The window also stops at
# the end of the note and at the first " FROM ", so "referred to JRRH from
# Kakira" and "referred to the hospital from Mulago" are not referrals out.
WINDOW = 60

# The notes read, one row each: the clinician's four free-text fields and the
# triage notes. Each is cut to NOTE_CHARS as ordinary text. Left as
# nvarchar(max), every one of the phrase and destination tests re-read the
# whole note as a large object, and October 2026 took minutes instead of
# seconds; no note at Jinja comes near the limit.
NOTE_FIELDS = ("PresentingComplaint", "ProvisionalDiagnosis", "ClinicalNotes", "TreatmentPlan")
NOTE_CHARS = 4000

# The attendance CTE each kind of script carries, and the columns it bands by:
# the SQL-only script bands in SQL (`s`), the Python and PowerShell scripts
# band afterwards from age in years and the sex code (`b`).
BASES = {"s": ("band", "sex", "visit"), "b": ("age_years", "sex", "visit_category")}


def _in(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _phrase_test() -> str:
    for p in OUT_PHRASES:
        if "'" in p:
            raise ValueError(f"phrase {p!r} contains a quote")
    return ", ".join(f"(CHARINDEX('{p}', nt.t))" for p in OUT_PHRASES)


def ctes(db: str, start, end_exclusive, base: str) -> str:
    """The referral CTEs, to follow the attendance CTE `base` ('s' or 'b') in
    the same WITH. Every lookup is a set: the referral visits of the period,
    the visits with a referral form, and the notes that mention a referral at
    all, each gathered once and joined to the attendance, so the plan never
    looks a visit up row by row.

    Produces `orf`: one row per attendance with the base's banding columns and
    the flags or01, or02_form and or02_note."""
    s, e = start.isoformat(), end_exclusive.isoformat()
    keep = ", ".join(f"{base}.{c}" for c in BASES[base])
    fields = ",\n                                ".join(
        f"(CAST(c.{f} AS nvarchar({NOTE_CHARS})))" for f in NOTE_FIELDS)
    return f"""ori AS (
    /* OR01: visits of the period registered as a referral, unless the
       referrer is recorded as SELF. */
    SELECT  rv.VisitNo
    FROM    {db}.dbo.Visits rv
    WHERE   rv.VisitDate >= '{s}'
      AND   rv.VisitDate <  '{e}'
      AND   rv.VisitCategoryID IN ({_in(REFERRAL_IN_CATEGORIES)})
      AND   UPPER(LTRIM(RTRIM(ISNULL(rv.ReferredBy, '')))) NOT LIKE '{SELF_REFERRER}%'
), ore AS (
    /* OR02, the form: visits with an external referral form, once each. */
    SELECT  DISTINCT er.VisitNo
    FROM    {db}.dbo.ExternalReferrals er
), orn AS (
    /* OR02, the notes: every note on these attendances that mentions a
       referral or a transfer at all, one row per note. */
    SELECT  n.VisitNo, ' ' + UPPER(REPLACE(REPLACE(REPLACE(n.t, CHAR(13), ' '), CHAR(10), ' '), CHAR(9), ' ')) + ' ' AS t
    FROM   (SELECT  c.VisitNo, f.t
            FROM    {base}
            JOIN    {db}.dbo.ClinicalFindings c ON c.VisitNo = {base}.VisitNo
            CROSS APPLY (VALUES {fields}) f(t)
            UNION ALL
            SELECT  tg.TreatmentNo, CAST(tg.Notes AS nvarchar({NOTE_CHARS}))
            FROM    {base}
            JOIN    {db}.dbo.Triage tg ON tg.TreatmentNo = {base}.VisitNo) n
    WHERE   n.t LIKE '%REF%' OR n.t LIKE '%TRANSF%'
), orh AS (
    /* ...of which those that refer the client to a named facility outside
       JRRH: a phrase, then within the window - cut at the end of the note and
       at the first FROM - a destination. Once per visit. */
    SELECT  DISTINCT nt.VisitNo
    FROM    orn nt
    CROSS APPLY (VALUES {_phrase_test()}) ph(p)
    CROSS APPLY (SELECT SUBSTRING(nt.t, ph.p, {WINDOW}) + '|' AS w) w0
    CROSS APPLY (SELECT LEFT(w0.w, CHARINDEX('|', w0.w) - 1) + ' FROM ' AS w) w1
    CROSS APPLY (SELECT LEFT(w1.w, CHARINDEX(' FROM ', w1.w) - 1) AS w) w2
    WHERE   ph.p > 0
      AND   {like_any("w2.w", DESTINATIONS)}
), orf AS (
    SELECT  {keep},
            CASE WHEN ori.VisitNo IS NULL THEN 0 ELSE 1 END AS or01,
            CASE WHEN ore.VisitNo IS NULL THEN 0 ELSE 1 END AS or02_form,
            CASE WHEN orh.VisitNo IS NULL THEN 0 ELSE 1 END AS or02_note
    FROM    {base}
    LEFT JOIN ori ON ori.VisitNo = {base}.VisitNo
    LEFT JOIN ore ON ore.VisitNo = {base}.VisitNo
    LEFT JOIN orh ON orh.VisitNo = {base}.VisitNo
)"""


def _codes_apply(prefix: str) -> str:
    p = prefix
    return f"""CROSS APPLY (VALUES
        (CASE WHEN f.or01 = 1 THEN '{p}OR01' END),
        (CASE WHEN f.or02_form = 1 OR f.or02_note = 1 THEN '{p}OR02' END)
    ) rc(code)"""


def strata_select(prefix: str) -> str:
    """OR01 and OR02 as upload rows, in one pass over `orf` built on `s`."""
    return f"""SELECT  rc.code AS diagnosis, f.band, f.sex, f.visit, COUNT(*) AS n
FROM    orf f
{_codes_apply(prefix)}
WHERE   rc.code IS NOT NULL
GROUP BY rc.code, f.band, f.sex, f.visit"""


def raw_select(prefix: str) -> str:
    """The same two lines in the shape the Python and PowerShell scripts read,
    over `orf` built on `b` (age in years, sex code, visit category), so the
    script bands them with the function it bands attendance with."""
    return f"""SELECT  f.age_years, f.sex, f.visit_category, rc.code AS diagnosis, COUNT(*) AS n
FROM    orf f
{_codes_apply(prefix)}
WHERE   rc.code IS NOT NULL
GROUP BY f.age_years, f.sex, f.visit_category, rc.code"""


def records_select() -> str:
    """Every attendance by band, sex, visit and the three flags, with OR02's
    two halves kept apart, over `orf` built on `s`: counts only, no identifier
    of any kind. Used to check the upload rows against an independent tally."""
    return """SELECT  f.band, f.sex, f.visit, f.or01, f.or02_form, f.or02_note, COUNT(*) AS n
FROM    orf f
GROUP BY f.band, f.sex, f.visit, f.or01, f.or02_form, f.or02_note"""


def codes() -> list:
    """Every 105:01 code this module can emit."""
    return ["OR01", "OR02"]
