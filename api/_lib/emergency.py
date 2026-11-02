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

Jinja last filled the section by hand for June and July 2026 (ES01 781 and 866;
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
    casualty's own ward, 40440 "ACCIDENTS & EMERGENCY", and many stayed there on
    paper for days; from September most were booked straight onto destination
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
July were reported on paper at 23 and 27 deaths at the unit, while the EMR
holds 7 and 4 deaths of casualty clients within a WEEK of arrival - so ES09
from this extract is a minimum, and the paper register should be preferred
while the two disagree. The same is true, less severely, of ES07b. A death
within a day of arrival on a ward the client had already reached is counted,
and a client brought in dead whose death was registered is counted; neither
can be told apart in the EMR.
"""

# The casualty community, as GetLookupDataDes returns it. Kept in step with
# extract_scripts.ENTRY_POINT_COMMUNITIES, which names the same department for
# the attendance rule; scripts/test_emergency.py holds the two together.
EMERGENCY_COMMUNITIES = ("ACCIDENT AND EMERGENCY",)

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


def _clean(expr: str) -> str:
    """Upper-case free text with line breaks and tabs flattened, so a pattern
    never fails on a line break and the TSV a grid is copied into never tears."""
    return (f"UPPER(REPLACE(REPLACE(REPLACE(ISNULL(CAST({expr} AS nvarchar(max)), ''), "
            f"CHAR(13), ' '), CHAR(10), ' '), CHAR(9), ' '))")


def ctes(db: str, start, end_exclusive) -> str:
    """The emergency CTEs, to follow an existing `comm` CTE in the same WITH.

    `comm` resolves each community the period used to its name once, as the
    attendance query already does. Every CTE here is referenced exactly once
    downstream, so SQL Server builds each a single time; the first draft
    referenced its classification from five UNION branches and ran for minutes.

    Produces `ecls`: one row per A&E visit with VisitNo, PatientNo, VisitDate,
    BirthDate, GenderID and the flags cat ('a' medical, 'b' obs/gyn,
    'c' surgical, 'd' RTI), mode ('a'-'e', RTI only), haem, ctrl, died."""
    s, e = start.isoformat(), end_exclusive.isoformat()
    names = _in(EMERGENCY_COMMUNITIES)
    t = "x.t"
    tb = "x.tb"
    return f"""ae AS (
    SELECT  vv.VisitNo, vv.PatientNo, vv.VisitDate, vv.DoctorSpecialtyID
    FROM    {db}.dbo.Visits vv
    JOIN    comm ON comm.CommunityID = vv.CommunityID
    WHERE   vv.VisitDate >= '{s}'
      AND   vv.VisitDate <  '{e}'
      AND   LTRIM(RTRIM(ISNULL(comm.name, ''))) IN ({names})
), eadm AS (
    /* The admission this casualty visit became, if any, and where its bed was. */
    SELECT  a.VisitNo, a.AdmissionNo, r.WardsID,
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
    SELECT  VisitNo,
            MAX(CASE WHEN DiseaseCode LIKE 'PA0%' OR DiseaseCode LIKE 'PD5%' OR DiseaseCode LIKE 'PF6%'
                     THEN 1 ELSE 0 END) AS dx_rti,
            MAX(CASE WHEN DiseaseCode LIKE 'J%' OR DiseaseCode LIKE 'GA%' THEN 1 ELSE 0 END) AS dx_obs,
            MAX(CASE WHEN DiseaseCode LIKE 'N[A-F]%' OR DiseaseCode LIKE 'ORTH%' THEN 1 ELSE 0 END) AS dx_surg
    FROM    edx GROUP BY VisitNo
), erd AS (
    /* The first ward round of each admission, gathered in one join rather than
       looked up per visit: IPDDoctor is not indexed on AdmissionNo, and the
       per-visit lookup made a five-month run take four minutes. */
    SELECT  rd.AdmissionNo,
            CONCAT(ic.History, ' | ', ic.ClinicalDiagnosis, ' | ', ic.ClinicalNotes, ' | ', ic.TreatmentPlan) AS t,
            ROW_NUMBER() OVER (PARTITION BY rd.AdmissionNo ORDER BY rd.RoundDateTime, rd.RoundNo) AS k
    FROM    eadm m
    JOIN    {db}.dbo.IPDDoctor rd ON rd.AdmissionNo = m.AdmissionNo
    JOIN    {db}.dbo.IPDClinicalFindings ic ON ic.RoundNo = rd.RoundNo
    WHERE   m.k = 1
), etxt AS (
    /* Everything written about the casualty episode, as one upper-case string. */
    SELECT  ae.VisitNo, ae.PatientNo, ae.VisitDate, ae.DoctorSpecialtyID,
            m.AdmissionNo, m.WardsID,
            ' ' + {_clean("CONCAT(cf.t, ' | ', tr.t, ' | ', ad.t, ' | ', rd.t, ' | ', ex.t)")} + ' ' AS t
    FROM    ae
    LEFT JOIN eadm m ON m.VisitNo = ae.VisitNo AND m.k = 1
    OUTER APPLY (SELECT TOP 1 CONCAT(c.PresentingComplaint, ' | ', c.ProvisionalDiagnosis, ' | ',
                                     c.ClinicalNotes, ' | ', c.TreatmentPlan, ' | ', c.MuscularSkeletal,
                                     ' | ', c.Skin) AS t
                 FROM {db}.dbo.ClinicalFindings c WHERE c.VisitNo = ae.VisitNo) cf
    OUTER APPLY (SELECT TOP 1 tg.Notes AS t
                 FROM {db}.dbo.Triage tg WHERE tg.TreatmentNo = ae.VisitNo) tr
    OUTER APPLY (SELECT TOP 1 a.AdmissionNotes AS t
                 FROM {db}.dbo.Admissions a WHERE a.AdmissionNo = m.AdmissionNo) ad
    LEFT JOIN erd rd ON rd.AdmissionNo = m.AdmissionNo AND rd.k = 1
    OUTER APPLY (SELECT TOP 1 CONCAT(ex1.PresentingSignsAndSymptoms, ' | ', ex1.Diagnosis) AS t
                 FROM {db}.dbo.Examinations ex1 WHERE ex1.VisitNo = ae.VisitNo) ex
), ecls AS (
    SELECT  x.VisitNo, p.BirthDate, p.GenderID, x.VisitDate,
            x.rti,
            CASE WHEN x.rti = 1 THEN 'd'
                 WHEN p.GenderID = '15F'
                      AND DATEDIFF(day, p.BirthDate, x.VisitDate) >= 3653
                      AND (x.dx_obs = 1 OR x.DoctorSpecialtyID IN ({_in(GYN_SPECIALTIES)})
                           OR x.WardsID IN ({_in(GYN_WARDS)}) OR {like_any(t, OBS_TERMS)}) THEN 'b'
                 WHEN x.dx_surg = 1 OR x.DoctorSpecialtyID IN ({_in(SURGICAL_SPECIALTIES)})
                      OR x.WardsID IN ({_in(SURGICAL_WARDS)}) OR {like_any(t, SURGICAL_TERMS)} THEN 'c'
                 ELSE 'a' END AS cat,
            CASE WHEN x.rti = 0 THEN NULL
                 WHEN {like_any(t, PEDESTRIAN_TERMS)} AND NOT {like_any(t, ON_VEHICLE_TERMS)} THEN 'd'
                 WHEN {like_any(t, BICYCLE_TERMS)} THEN 'c'
                 WHEN {like_any(t, MOTORCYCLE_TERMS)} THEN 'b'
                 WHEN {like_any(t, MOTOR_VEHICLE_TERMS)} THEN 'a'
                 ELSE 'e' END AS mode,
            CASE WHEN {like_any(tb, EXTERNAL_BLEED_TERMS)} THEN 1 ELSE 0 END AS haem,
            CASE WHEN {like_any(t, CONTROLLED_TERMS)}
                      OR EXISTS (SELECT 1 FROM {db}.dbo.Items it
                                 WHERE it.VisitNo = x.VisitNo AND {like_any("UPPER(it.ItemName)", CONTROL_ITEM_TERMS)})
                 THEN 1 ELSE 0 END AS ctrl,
            CASE WHEN EXISTS (SELECT 1 FROM {db}.dbo.Deaths dt
                              WHERE dt.PatientNo = x.PatientNo
                                AND dt.DeathDate >= CAST(x.VisitDate AS date)
                                AND dt.DeathDate <  DATEADD(day, 2, CAST(x.VisitDate AS date)))
                      OR EXISTS (SELECT 1 FROM {db}.dbo.Discharges ds
                                 WHERE ds.AdmissionNo = x.AdmissionNo
                                   AND ds.DischargeStatusID = '{DECEASED}'
                                   AND ds.DischargeDateTime < DATEADD(day, 2, CAST(x.VisitDate AS date)))
                 THEN 1 ELSE 0 END AS died
    FROM   (SELECT et.*, ISNULL(f.dx_rti, 0) AS dx_rti, ISNULL(f.dx_obs, 0) AS dx_obs,
                   ISNULL(f.dx_surg, 0) AS dx_surg,
                   CASE WHEN f.dx_rti = 1 OR {like_any("et.t", RTI_TERMS)}
                             OR ({like_any("et.t", VEHICLE_TERMS)} AND {like_any("et.t", VEHICLE_EVENT_TERMS)})
                        THEN 1 ELSE 0 END AS rti,
                   {_strip("et.t", NOT_BLEEDING)} AS tb
            FROM etxt et LEFT JOIN edxf f ON f.VisitNo = et.VisitNo) x
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
