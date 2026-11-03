"""HMIS 105:01 section 1.3.25, Emergency Medical Services, from ClinicMaster.

WHAT THE FORM ASKS FOR, AND WHAT THIS FILLS

Four lines on the live 105:01 form at hmis.health.go.ug, read on 2 November 2026
from data entry form ONHrPgcJfZI:

    ES01  Number of emergency cases at the facility
          a Medical · b Obstetrics/gynaecology · c Surgical · d Road traffic injuries
    ES07  No. of patients with external haemorrhages      a Total · b Controlled
    ES08  Road traffic injuries
          a Motor vehicle · b Motor cycle · c Bicycle · d Pedestrian · e Other
    ES09  No. of deaths at emergency unit
          a Medical · b Obstetrics/gynaecology · c Surgical · d Road traffic injuries

all by the OPD age bands and sex. ES01b carries boxes for women of 10-19 and 20+
only, and ES09b for 10-19 and 20+; nothing is written to a box the form does
not draw.

Jinja last reported the section in eHMIS for June and July 2026 (ES01 781 and 866;
ES07 55/51 and 51/47; ES09 23 and 27). From August, when the compiler took over
the 105:01, it has been empty, because no line of it is a diagnosis and the
extract only ever translated diagnoses.

WHERE THE FACTS ACTUALLY ARE

ClinicMaster has a full emergency module - EmergencyRegistration, the airway,
breathing and circulation surveys, EmergencyPresentIllnessHistory with mechanism
of injury, EmergencyUnitExit with outcome - and at Jinja it is empty: 14
registrations and one exit record in the whole database, the surveys none at
all. Measured 2 November 2026.

What is filled is the visit, its free text and what happened to it:

  * every client seen in casualty has a visit whose community is ACCIDENT AND
    EMERGENCY (1,147 in August, 1,050 in September, 1,261 in October);
  * 85 per cent of those visits carry clinical text - the presenting complaint,
    provisional diagnosis and notes in ClinicalFindings, triage notes, the
    admission note, the first ward round - and that is where "RTA, knocked by a
    speeding motorcycle while crossing the road" is written;
  * coded diagnoses exist for only about a quarter of them (212 of 3,458 at the
    visit, 705 within a fortnight on the ward), so codes are used where present
    and never relied on alone;
  * casualty books its admissions in the EMR, but where the bed is booked says
    little about where the client is: until August most were booked onto
    casualty's own ward, 40440 "ACCIDENTS & EMERGENCY", and many were nominally
    kept there for days; from September most were booked straight onto destination
    wards, including the eye wards (146 in September) and the TB ward (257 in
    October), which were plainly holding general admissions;
  * WardTransfer is no record of leaving casualty: its first row for an
    admission is the admission's own placement (from and to the same ward),
    written at admission, so nearly every admission has one.

So each line below is a rule over those records, applied once per A&E visit, and
every rule is written here where it can be read and argued with.

THE RULES

Case.       Every visit in the period whose community is ACCIDENT AND EMERGENCY,
            whether or not it ended in admission. One visit, one case.

Category.   Exactly one per case, tested in this order so the four ES01 lines
            add up to the case count:
              RTI      road-traffic wording in the text, or an ICD-11 transport
                       external cause (PA0, PD5, PF6) on the record;
              Obs/gyn  a woman of 10 or over with a pregnancy or gynaecological
                       code (ICD-11 J, GA), a gynaecologist, a gynaecology or
                       postnatal bed, or pregnancy wording in the text;
              Surgical injury chapter or ORTH codes, a surgeon, orthopaedic,
                       dental, ENT or eye clinician, a bed on a surgical or the
                       orthopaedic ward, or injury and surgical wording in the
                       text. Eye-ward beds do not count: since September they
                       have held casualty's general overflow;
              Medical  everything else.

ES08 mode.  For RTI cases only, the injured person's role, from the text:
              Pedestrian    pedestrian, crossing, walking, knocked down/by, run
                            over - unless the text also puts them on a vehicle;
              Bicycle       bicycle or cyclist;
              Motor cycle   boda boda, motorcycle in any of its spellings;
              Motor vehicle car, vehicle, taxi, bus, lorry, truck, trailer;
              Other         an RTI whose text names no road user.

ES07a.      Visible external bleeding: lacerations, cut, stab, degloving or open
            wounds, open fractures, or a bleeding wound or scalp, read after
            "no bleeding" and its variants have been removed from the text.
            Nose, ear, gut, vaginal and internal bleeding are not external
            haemorrhage and do not count.

ES07b.      ES07a cases whose record says how the bleeding was dealt with:
            sutured, stitched, wound toilet, pressure dressing, tourniquet,
            haemostasis, packing, debridement, "bleeding controlled", or a wound
            dressing, suturing or debridement billed to the visit. This is a
            floor: control that was done and not written down cannot be seen.

ES09.       A death at the unit, read as a death within a day of arriving at
            casualty: a death register entry dated the day of the casualty
            visit or the day after, or the visit's admission discharged
            Deceased by the end of the day after. The register keeps the date
            only (every entry since June is at midnight), so "within a day" is
            the arrival day and the next. Where the bed was booked is not
            used, for the reasons above. The category is the case's own.

WHAT THIS CANNOT SEE

Deaths are the weak line. ClinicMaster's death recording is thin - June and
July were reported in eHMIS at 23 and 27 deaths at the unit, while the EMR
holds 7 and 4 deaths of casualty clients within a WEEK of arrival - so ES09
from this extract is a minimum, and the source those reported figures were
compiled from should be preferred while the two disagree. The same is true, less severely, of ES07b. A death
within a day of arrival on a ward the client had already reached is counted,
and a client brought in dead whose death was registered is counted; neither
can be told apart in the EMR.
"""

# The casualty community, as GetLookupDataDes returns it. Kept in step with
# extract_scripts.ENTRY_POINT_COMMUNITIES, which names the same department for
# the attendance rule; scripts/test_emergency.py holds the two together.
EMERGENCY_COMMUNITIES = ("ACCIDENT AND EMERGENCY",)
# ...and the community code that name resolves to. Casualty's visits are found
# by the code: matched through the lookup function, the server could not tell
# how many there were, assumed a handful, and recomputed the casualty list for
# every casualty visit. 507BUV is the only code GetLookupDataDes resolves to
# ACCIDENT AND EMERGENCY among 2026's visits (10,634 to October, read 3 November
# 2026); scripts/test_emergency.py holds the name and the code together.
EMERGENCY_COMMUNITY_CODES = ("507BUV",)

# Casualty's own beds. Rooms.WardsID for ward "ACCIDENTS & EMERGENCY". Not used
# for any line - see "Where the facts actually are" - and kept for the profile
# script and the tests, which hold the rules to that decision.
EMERGENCY_WARD = "40440"

# Wards and clinicians that settle a category on their own, as lookup codes.
GYN_WARDS = ("4011", "4008")                    # GYN WARD, POSTNATAL WARD
SURGICAL_WARDS = ("4004", "4005", "4010")       # F/M surgical, orthopaedic
# Not 4006/4007, the eye wards: 146 casualty admissions were booked onto them in
# September 2026 against 5 in June-August, which is overflow, not eye surgery.
GYN_SPECIALTIES = ("39GYN",)
SURGICAL_SPECIALTIES = ("39SUR", "39OTH", "39ENT", "39DS", "39DEN", "39OP", "39DEN26")

DECEASED = "35D"

# Free-text patterns, matched against the record's text upper-cased and padded
# with a space at each end, so [^A-Z] works as a word boundary at the edges too.
# LIKE patterns, not regular expressions: % is any run, [^A-Z] one non-letter.
RTI_TERMS = (
    "[^A-Z]RTA[^A-Z]", "[^A-Z]RTI[^A-Z]", "R.T.A", "R/T/A", "ROAD TRAFFIC", "TRAFFIC ACC",
    "MOTOR ACCIDENT", "BODA", "PIKIPIKI", "COLLISION", "COLLIDED", "PEDESTRIAN",
    "[^A-Z]MVA[^A-Z]", "[^A-Z]MCA[^A-Z]", "KNOCKED DOWN BY", "RUN OVER BY", "OVERTURNED",
)
# A vehicle word only means RTI next to an event word: "motorcycle" alone is a
# bystander's mode of transport to hospital as often as a mechanism of injury.
VEHICLE_TERMS = (
    "MOTORCYC", "MOTOCYC", "MOTOR CYC", "MOTORBIKE", "MOTOR BIKE", "MOTORCYLE", "BICYC", "BICYLE",
    "[^A-Z]CAR[^A-Z]", "VEHICLE", "TAXI", "LORRY", "TRUCK", "[^A-Z]BUS[^A-Z]", "TRAILER",
    "TIPPER", "MATATU", "MINIBUS", "TRACTOR",
)
VEHICLE_EVENT_TERMS = (
    "ACCIDENT", "KNOCK", "CRASH", "HIT BY", "FELL OFF", "FELL FROM", "THROWN OFF", "RAN OVER",
)

PEDESTRIAN_TERMS = (
    "PEDESTRIAN", "CROSSING", "WALKING", "KNOCKED DOWN", "KNOCKED BY", "RUN OVER", "RAN OVER",
)
ON_VEHICLE_TERMS = (
    "RIDING", "RIDER", "PASSENGER", "PILLION", "DRIVER", "DRIVING", "ON A MOTO", "ON ANOTHER",
    "ON A BODA", "ON BODA", "ON A BICYC", "ON HIS MOTO", "ON HER MOTO", "FELL OFF", "FELL FROM",
    "THROWN OFF", "OCCUPANT", "INSIDE A", "IN A TAXI", "IN A BUS", "IN A CAR",
)
BICYCLE_TERMS = ("BICYC", "BICYLE", "CYCLIST", "PEDAL CYCLE")
MOTORCYCLE_TERMS = (
    "BODA", "MOTORCYC", "MOTOCYC", "MOTOR CYC", "MOTORBIKE", "MOTOR BIKE", "MOTORCYLE",
    "[^A-Z]MCA[^A-Z]", "PIKIPIKI",
)
MOTOR_VEHICLE_TERMS = (
    "[^A-Z]CAR[^A-Z]", "VEHICLE", "TAXI", "LORRY", "TRUCK", "[^A-Z]BUS[^A-Z]", "TRAILER",
    "TIPPER", "MATATU", "MINIBUS", "[^A-Z]MVA[^A-Z]", "TRACTOR", "PICK UP", "PICKUP",
)

OBS_TERMS = (
    "PREGNAN", "GRAVID", "ABORTION", "MISCARR", "ECTOPIC", "IN LABOUR", "LABOUR PAIN",
    "ANTEPARTUM", "POSTPARTUM", "PUERPER", "PV BLEED", "VAGINAL BLEED", "PER VAGINA",
    "OBSTETRIC", "[^A-Z]G[0-9]P[0-9]", "[0-9]WOA", " WOA[^A-Z]", "GESTATION",
)
SURGICAL_TERMS = (
    "FRACTURE", "[^A-Z]#", "INJUR", "TRAUMA", "WOUND", "LACERAT", "ASSAULT", "[^A-Z]BURN", "SCALD",
    "STAB WOUND", "STABBED", "DOG BITE", "ANIMAL BITE", "HUMAN BITE", "ACUTE ABDOMEN",
    "APPENDIC", "HERNIA", "INTESTINAL OBSTRUCTION", "BOWEL OBSTRUCTION", "URINARY RETENTION",
    "RETENTION OF URINE", "ABSCESS", "DISLOCAT", "PERITONITIS", "[^A-Z]TBI[^A-Z]", "DEGLOV",
    "AMPUTAT", "GANGRENE", "FOREIGN BODY", "FELL FROM", "FALL FROM", "CUT WOUND",
)

# Bleeding: the negations are deleted first, then the positive wording sought.
NOT_BLEEDING = (
    "NO ACTIVE BLEEDING", "NOT ACTIVELY BLEEDING", "NO BLEEDING", "NOT BLEEDING",
    "NO HX OF BLEEDING", "NO HISTORY OF BLEEDING", "NO H/O BLEEDING", "NIL BLEEDING",
)
EXTERNAL_BLEED_TERMS = (
    "LACERAT", "CUT WOUND", "CUT ON THE", "DEEP CUT", "STAB WOUND", "STABBED", "DEGLOV",
    "OPEN WOUND", "OPEN FRACTURE", "BLEEDING WOUND", "BLEEDING FROM THE WOUND",
    "BLEEDING FROM WOUND", "BLEEDING FROM THE SITE", "BLEEDING FROM THE SCALP",
    "BLEEDING FROM SCALP", "SCALP BLEED", "ACTIVELY BLEEDING", "ACTIVE BLEEDING",
    "BLEEDING PROFUSELY", "PROFUSE BLEEDING", "BLEEDING WOUNDS",
)
CONTROLLED_TERMS = (
    "SUTUR", "STITCH", "WOUND TOILET", "TOILET AND", "TOILETING", "PRESSURE DRESSING",
    "PRESSURE BANDAGE", "TOURNIQUET", "HAEMOSTASIS", "HEMOSTASIS", "PACKING", "PACKED",
    "DEBRIDE", "BLEEDING CONTROLLED", "BLEEDING WAS CONTROLLED", "BLEEDING STOPPED",
    "CONTROLLED BLEEDING", "WOUND DRESSING", "DRESSING DONE", "WAS DRESSED",
)
CONTROL_ITEM_TERMS = ("DRESSING", "SUTUR", "DEBRED", "DEBRID", "STITCH", "TOILET")

# Death in the text is not used: "mother died", "baby died", "no deaths in the
# family" and brought-in-dead all read the same to LIKE, and a death count that
# might be someone else's death is worse than a short one.


def like_any(col: str, terms) -> str:
    """OR of LIKE '%term%' over one column. Terms are constants defined here,
    never user input; the quote check is a guard against a careless edit."""
    for t in terms:
        if "'" in t:
            raise ValueError(f"pattern {t!r} contains a quote")
    return "(" + " OR ".join(f"{col} LIKE '%{t}%'" for t in terms) + ")"


def _in(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


# The notes read for each casualty episode, one row each: the clinician's six
# free-text fields, the triage notes, the admission note, the first ward round's
# four fields and the examination. Each is cut to NOTE_CHARS as ordinary text.
# Joined into one large-object string, as the first version did, every one of
# the 170-odd patterns below re-read the whole record, and October 2026 took
# 7 minutes 48 seconds; read note by note, a LIKE over a whole record is simply
# a LIKE over any of its notes, so the rules are unchanged.
NOTE_CHARS = 4000

# The notes are upper-cased before any pattern is tried, so the patterns are
# compared code point by code point: under the server's case-insensitive
# collation every LIKE '%...%' re-folds case across the whole note, and with
# 170-odd patterns over some 17,000 notes a month that is most of the run.
BINARY = "Latin1_General_BIN2"

# Each emergency CTE is computed once and then joined. Without this the
# optimiser pushed the visit number into them and recomputed casualty's visit
# list - two scans of Visits - for every casualty visit: 234 scans for three
# days, about 2,600 for a month, and nearly all of the 7 min 48 s October took.
# A TOP cannot be pushed through, so the cap (larger than any table here) keeps
# every row and stops the correlation.
ONCE = "TOP (2147483647)"


def _note(expr: str) -> str:
    return f"(CAST({expr} AS nvarchar({NOTE_CHARS})))"


def ctes(db: str, start, end_exclusive) -> str:
    """The emergency CTEs, to follow the attendance CTEs in the same WITH.

    Casualty's visits are found by community code (EMERGENCY_COMMUNITY_CODES),
    each CTE is computed once (ONCE) and the notes are read one at a time as
    ordinary text compared code point by code point (NOTE_CHARS, BINARY):
    together those took October 2026 from 7 min 48 s to well under a minute
    with the same counts. The first draft referenced its classification from
    five UNION branches and ran for minutes, so the classification is read by
    one branch only.

    Produces `ecls`: one row per A&E visit with VisitNo, PatientNo, VisitDate,
    BirthDate, GenderID and the flags cat ('a' medical, 'b' obs/gyn,
    'c' surgical, 'd' RTI), mode ('a'-'e', RTI only), haem, ctrl, died."""
    s, e = start.isoformat(), end_exclusive.isoformat()
    codes = _in(EMERGENCY_COMMUNITY_CODES)
    notes = ",\n                        ".join(
        [_note(f"cf.{c}") for c in ("PresentingComplaint", "ProvisionalDiagnosis", "ClinicalNotes",
                                    "TreatmentPlan", "MuscularSkeletal", "Skin")]
        + [_note("tr.Notes"), _note("ad.AdmissionNotes")]
        + [_note(f"rd.{c}") for c in ("History", "ClinicalDiagnosis", "ClinicalNotes", "TreatmentPlan")]
        + [_note(f"ex.{c}") for c in ("PresentingSignsAndSymptoms", "Diagnosis")])

    def flag(terms, col="n.t"):
        return f"MAX(CASE WHEN {like_any(col, terms)} THEN 1 ELSE 0 END)"

    return f"""ae AS (
    SELECT  {ONCE} vv.VisitNo, vv.PatientNo, vv.VisitDate, vv.DoctorSpecialtyID
    FROM    {db}.dbo.Visits vv
    WHERE   vv.VisitDate >= '{s}'
      AND   vv.VisitDate <  '{e}'
      AND   vv.CommunityID IN ({codes})
), eadm AS (
    /* The admission this casualty visit became, if any, and where its bed was. */
    SELECT  {ONCE} a.VisitNo, a.AdmissionNo, r.WardsID,
            ROW_NUMBER() OVER (PARTITION BY a.VisitNo ORDER BY a.AdmissionDateTime, a.AdmissionNo) AS k
    FROM    {db}.dbo.Admissions a
    JOIN    ae ON ae.VisitNo = a.VisitNo
    LEFT JOIN {db}.dbo.Beds b  ON b.BedNo  = a.BedNo
    LEFT JOIN {db}.dbo.Rooms r ON r.RoomNo = b.RoomNo
), edx AS (
    /* Codes recorded for the visit, for its admission and for its ward rounds. */
    SELECT  ae.VisitNo, d.DiseaseCode
    FROM    ae JOIN {db}.dbo.Diagnosis d ON d.TreatmentNo = ae.VisitNo AND d.ObjectName = 'Visits'
    UNION ALL
    SELECT  m.VisitNo, d.DiseaseCode
    FROM    eadm m JOIN {db}.dbo.Diagnosis d ON d.TreatmentNo = m.AdmissionNo AND d.ObjectName = 'Admissions'
    WHERE   m.k = 1
    UNION ALL
    SELECT  m.VisitNo, d.DiseaseCode
    FROM    eadm m
    JOIN    {db}.dbo.IPDDoctor rd ON rd.AdmissionNo = m.AdmissionNo
    JOIN    {db}.dbo.Diagnosis d ON d.TreatmentNo = rd.RoundNo AND d.ObjectName = 'IPDDoctor'
    WHERE   m.k = 1
), edxf AS (
    SELECT  {ONCE} VisitNo,
            MAX(CASE WHEN DiseaseCode LIKE 'PA0%' OR DiseaseCode LIKE 'PD5%' OR DiseaseCode LIKE 'PF6%'
                     THEN 1 ELSE 0 END) AS dx_rti,
            MAX(CASE WHEN DiseaseCode LIKE 'J%' OR DiseaseCode LIKE 'GA%' THEN 1 ELSE 0 END) AS dx_obs,
            MAX(CASE WHEN DiseaseCode LIKE 'N[A-F]%' OR DiseaseCode LIKE 'ORTH%' THEN 1 ELSE 0 END) AS dx_surg
    FROM    edx GROUP BY VisitNo
), erd AS (
    /* The first ward round of each admission, gathered in one join rather than
       looked up per visit: IPDDoctor is not indexed on AdmissionNo, and the
       per-visit lookup made a five-month run take four minutes. */
    SELECT  {ONCE} rd.AdmissionNo, ic.History, ic.ClinicalDiagnosis, ic.ClinicalNotes, ic.TreatmentPlan,
            ROW_NUMBER() OVER (PARTITION BY rd.AdmissionNo ORDER BY rd.RoundDateTime, rd.RoundNo) AS k
    FROM    eadm m
    JOIN    {db}.dbo.IPDDoctor rd ON rd.AdmissionNo = m.AdmissionNo
    JOIN    {db}.dbo.IPDClinicalFindings ic ON ic.RoundNo = rd.RoundNo
    WHERE   m.k = 1
), enote AS (
    /* Everything written about the casualty episode, one row per note, as
       ordinary upper-case text padded with a space at each end. */
    SELECT  ae.VisitNo,
            (' ' + UPPER(REPLACE(REPLACE(REPLACE(f.t, CHAR(13), ' '), CHAR(10), ' '), CHAR(9), ' ')) + ' ')
                COLLATE {BINARY} AS t
    FROM    ae
    LEFT JOIN eadm m ON m.VisitNo = ae.VisitNo AND m.k = 1
    OUTER APPLY (SELECT TOP 1 c.PresentingComplaint, c.ProvisionalDiagnosis, c.ClinicalNotes,
                              c.TreatmentPlan, c.MuscularSkeletal, c.Skin
                 FROM {db}.dbo.ClinicalFindings c WHERE c.VisitNo = ae.VisitNo) cf
    OUTER APPLY (SELECT TOP 1 tg.Notes
                 FROM {db}.dbo.Triage tg WHERE tg.TreatmentNo = ae.VisitNo) tr
    OUTER APPLY (SELECT TOP 1 a.AdmissionNotes
                 FROM {db}.dbo.Admissions a WHERE a.AdmissionNo = m.AdmissionNo) ad
    LEFT JOIN erd rd ON rd.AdmissionNo = m.AdmissionNo AND rd.k = 1
    OUTER APPLY (SELECT TOP 1 ex1.PresentingSignsAndSymptoms, ex1.Diagnosis
                 FROM {db}.dbo.Examinations ex1 WHERE ex1.VisitNo = ae.VisitNo) ex
    CROSS APPLY (VALUES {notes}) f(t)
    WHERE   f.t IS NOT NULL
), eflag AS (
    /* Each pattern family, once per note, gathered per visit: a family is
       present in the record when it is present in any of its notes. */
    SELECT  {ONCE} n.VisitNo,
            {flag(RTI_TERMS)} AS t_rti,
            {flag(VEHICLE_TERMS)} AS t_veh,
            {flag(VEHICLE_EVENT_TERMS)} AS t_vev,
            {flag(OBS_TERMS)} AS t_obs,
            {flag(SURGICAL_TERMS)} AS t_surg,
            {flag(PEDESTRIAN_TERMS)} AS t_ped,
            {flag(ON_VEHICLE_TERMS)} AS t_onv,
            {flag(BICYCLE_TERMS)} AS t_bic,
            {flag(MOTORCYCLE_TERMS)} AS t_moto,
            {flag(MOTOR_VEHICLE_TERMS)} AS t_mv,
            {flag(EXTERNAL_BLEED_TERMS, "nb.tb")} AS t_bleed,
            {flag(CONTROLLED_TERMS)} AS t_ctrl
    FROM    enote n
    CROSS APPLY (SELECT {_strip("n.t", NOT_BLEEDING)} AS tb) nb
    GROUP BY n.VisitNo
), eitem AS (
    /* A wound dressing, suturing or debridement billed to the casualty visit,
       gathered once rather than looked up visit by visit. */
    SELECT  DISTINCT {ONCE} it.VisitNo
    FROM    {db}.dbo.Items it
    JOIN    ae ON ae.VisitNo = it.VisitNo
    WHERE   {like_any("UPPER(it.ItemName)", CONTROL_ITEM_TERMS)}
), ecls AS (
    SELECT  x.VisitNo, p.BirthDate, p.GenderID, x.VisitDate,
            x.rti,
            CASE WHEN x.rti = 1 THEN 'd'
                 WHEN p.GenderID = '15F'
                      AND DATEDIFF(day, p.BirthDate, x.VisitDate) >= 3653
                      AND (x.dx_obs = 1 OR x.DoctorSpecialtyID IN ({_in(GYN_SPECIALTIES)})
                           OR x.WardsID IN ({_in(GYN_WARDS)}) OR x.t_obs = 1) THEN 'b'
                 WHEN x.dx_surg = 1 OR x.DoctorSpecialtyID IN ({_in(SURGICAL_SPECIALTIES)})
                      OR x.WardsID IN ({_in(SURGICAL_WARDS)}) OR x.t_surg = 1 THEN 'c'
                 ELSE 'a' END AS cat,
            CASE WHEN x.rti = 0 THEN NULL
                 WHEN x.t_ped = 1 AND x.t_onv = 0 THEN 'd'
                 WHEN x.t_bic = 1 THEN 'c'
                 WHEN x.t_moto = 1 THEN 'b'
                 WHEN x.t_mv = 1 THEN 'a'
                 ELSE 'e' END AS mode,
            x.t_bleed AS haem,
            CASE WHEN x.t_ctrl = 1 OR x.i_ctrl = 1 THEN 1 ELSE 0 END AS ctrl,
            CASE WHEN EXISTS (SELECT 1 FROM {db}.dbo.Deaths dt
                              WHERE dt.PatientNo = x.PatientNo
                                AND dt.DeathDate >= CAST(x.VisitDate AS date)
                                AND dt.DeathDate <  DATEADD(day, 2, CAST(x.VisitDate AS date)))
                      OR EXISTS (SELECT 1 FROM {db}.dbo.Discharges ds
                                 WHERE ds.AdmissionNo = x.AdmissionNo
                                   AND ds.DischargeStatusID = '{DECEASED}'
                                   AND ds.DischargeDateTime < DATEADD(day, 2, CAST(x.VisitDate AS date)))
                 THEN 1 ELSE 0 END AS died
    FROM   (SELECT  ae.VisitNo, ae.PatientNo, ae.VisitDate, ae.DoctorSpecialtyID,
                    m.AdmissionNo, m.WardsID,
                    ISNULL(f.dx_obs, 0) AS dx_obs, ISNULL(f.dx_surg, 0) AS dx_surg,
                    ISNULL(t.t_obs, 0) AS t_obs, ISNULL(t.t_surg, 0) AS t_surg,
                    ISNULL(t.t_ped, 0) AS t_ped, ISNULL(t.t_onv, 0) AS t_onv,
                    ISNULL(t.t_bic, 0) AS t_bic, ISNULL(t.t_moto, 0) AS t_moto,
                    ISNULL(t.t_mv, 0) AS t_mv, ISNULL(t.t_bleed, 0) AS t_bleed,
                    ISNULL(t.t_ctrl, 0) AS t_ctrl,
                    CASE WHEN i.VisitNo IS NULL THEN 0 ELSE 1 END AS i_ctrl,
                    CASE WHEN f.dx_rti = 1 OR t.t_rti = 1 OR (t.t_veh = 1 AND t.t_vev = 1)
                         THEN 1 ELSE 0 END AS rti
            FROM    ae
            LEFT JOIN eadm m  ON m.VisitNo = ae.VisitNo AND m.k = 1
            LEFT JOIN edxf f  ON f.VisitNo = ae.VisitNo
            LEFT JOIN eflag t ON t.VisitNo = ae.VisitNo
            LEFT JOIN eitem i ON i.VisitNo = ae.VisitNo) x
    JOIN    {db}.dbo.Patients p ON p.PatientNo = x.PatientNo
)"""


def _strip(expr: str, phrases) -> str:
    out = expr
    for p in phrases:
        if "'" in p:
            raise ValueError(f"phrase {p!r} contains a quote")
        out = f"REPLACE({out}, '{p}', ' ')"
    return out


def codes_apply(prefix: str) -> str:
    """CROSS APPLY that turns one classified case into the ES lines it counts
    towards: always one ES01, ES08 when RTI, ES07a/ES07b for bleeding, ES09 for
    a death. One pass over `ecls`, which is what keeps the query quick."""
    p = prefix
    return f"""CROSS APPLY (VALUES
        ('{p}ES01' + c.cat),
        (CASE WHEN c.rti = 1 THEN '{p}ES08' + c.mode END),
        (CASE WHEN c.haem = 1 THEN '{p}ES07a' END),
        (CASE WHEN c.haem = 1 AND c.ctrl = 1 THEN '{p}ES07b' END),
        (CASE WHEN c.died = 1 THEN '{p}ES09' + c.cat END)
    ) es(code)"""


def _age(alias: str) -> str:
    """Age at the visit in years, NULL for a missing or placeholder birth date -
    the same rule the attendance rows use."""
    return (f"CASE WHEN {alias}.BirthDate IS NULL OR {alias}.BirthDate < '1900-01-02' THEN NULL "
            f"ELSE CAST(DATEDIFF(day, {alias}.BirthDate, {alias}.VisitDate) AS float) / 365.25 END")


def strata_select(prefix: str, band_case, sexes: str) -> str:
    """The emergency rows in the five upload columns, banded in SQL.

    `band_case` is extract_scripts._band_case, passed in so the bands come from
    the one table every path shares; `sexes` is its VALUES list of sex codes.
    Visit is 'New' throughout: no ES line is split by new and repeat, and the
    upload insists on one of the two."""
    return f"""SELECT  es.code AS diagnosis, bd.band, sx.name AS sex, 'New' AS visit, COUNT(*) AS n
FROM    ecls c
JOIN    (VALUES {sexes}) AS sx(code, name) ON sx.code = c.GenderID
CROSS APPLY (SELECT {_age("c")} AS age_years) ag
CROSS APPLY (SELECT {band_case("ag.age_years")} AS band) bd
{codes_apply(prefix)}
WHERE   es.code IS NOT NULL
  AND   ag.age_years IS NOT NULL
GROUP BY es.code, bd.band, sx.name"""


def raw_select(prefix: str) -> str:
    """The emergency rows in the shape the Python and PowerShell scripts read -
    age in years, ClinicMaster's sex code, visit category, code, count - so the
    script bands them with the same function it bands attendance with."""
    return f"""SELECT  ag.age_years, c.GenderID AS sex, 'New' AS visit_category,
        es.code AS diagnosis, COUNT(*) AS n
FROM    ecls c
CROSS APPLY (SELECT {_age("c")} AS age_years) ag
{codes_apply(prefix)}
WHERE   es.code IS NOT NULL
GROUP BY ag.age_years, c.GenderID, es.code"""


def records_select(band_case, sexes: str) -> str:
    """One anonymous row per casualty case with every flag the rules set, and no
    identifier of any kind: month, band, sex and the flags. Used to check the
    aggregate against an independent tally, and to look at the rules' output."""
    return f"""SELECT  CONVERT(varchar(7), c.VisitDate, 120) AS month, bd.band, sx.name AS sex,
        c.cat, ISNULL(c.mode, '') AS mode, c.rti, c.haem, c.ctrl, c.died
FROM    ecls c
JOIN    (VALUES {sexes}) AS sx(code, name) ON sx.code = c.GenderID
CROSS APPLY (SELECT {_age("c")} AS age_years) ag
CROSS APPLY (SELECT {band_case("ag.age_years")} AS band) bd
WHERE   ag.age_years IS NOT NULL"""


def codes() -> list:
    """Every 105:01 code this module can emit, for the tests and the docs."""
    return (["ES01a", "ES01b", "ES01c", "ES01d", "ES07a", "ES07b"]
            + [f"ES08{x}" for x in "abcde"]
            + ["ES09a", "ES09b", "ES09c", "ES09d"])
