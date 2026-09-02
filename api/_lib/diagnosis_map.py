"""EMR free-text diagnosis -> HMIS 105 code translation.

Jinja RRH's EMR exports clinical diagnosis *names* (e.g. "ESSENTIAL
HYPERTENSION") in the DiagnosisCode column rather than HMIS 105 codes
(e.g. "CV02"). This module bridges the two so the raw monthly export can be
compiled directly.

Only clinically unambiguous, high-confidence mappings live in EMR_RULES.
Names that don't match fall through to OP01 "All others" (a real HMIS 105
OPD line) so they still count, and are surfaced in the upload's review list.

POLICY-SENSITIVE categories (HIV, TB) are isolated in POLICY_RULES and
default to OP01. HMIS 105 Section OPD has no dedicated HIV or TB diagnosis
line -- those are reported through the ART/HIV and TB program forms -- so a
records officer should decide deliberately how OPD attendances with these
diagnoses are counted. Change the codes here once that decision is made.
"""
import re

# --- Policy-sensitive: set deliberately by the records officer ---
# Default OP01 = "All others". HMIS105 has no plain HIV/TB OPD diagnosis line.
HIV_CODE = "OP01"
TB_CODE = "OP01"

POLICY_RULES = [
    # The spelled-out form matters. ClinicMaster's dictionary carries both
    # "HIV DISEASE CLINICAL STAGE 1 ..." and "HUMAN IMMUNODEFICIENCY VIRUS
    # DISEASE ASSOCIATED WITH MALARIA". Matching only the abbreviation sent the
    # second down the clinical rules, where the incidental mention of malaria
    # caught it and it was reported as a confirmed malaria case. A record is
    # classified by its subject, not by a co-morbidity named in passing.
    (r"\bHIV\b|HUMAN IMMUNODEFICIENCY VIRUS|RETROVIRAL DISEASE", HIV_CODE),
    (r"\bTUBERCULOSIS\b|\bTB\b(?! )|PULMONARY TB", TB_CODE),
]

# --- High-confidence clinical mappings (name substring -> HMIS105 code) ---
# Order matters: first match wins, so put specific patterns before general.
EMR_RULES = [
    (r"DIABETES IN PREGNAN", "MC05"),
    (r"DIABETES MELLITUS|\bDIABETES\b", "EM01"),
    (r"HIGH BLOOD PRESSURE IN PREGNAN", "MC04"),
    (r"HYPERTENS", "CV02"),
    (r"SICKLE CELL|SICKEL CELL", "NC01"),
    (r"\bEPILEPSY", "MH33"),
    (r"SCHIZOPHREN", "MH07"),
    (r"BIPOLAR", "MH08"),
    (r"MAJOR DEPRESS|DEPRESSIVE|DEPRESSION", "MH09"),
    (r"GENERAL, ?I?SED ANXIETY|GENERALIZED ANXIETY", "MH13"),
    (r"ANXIETY", "MH13"),
    (r"ACUTE.*PSYCHOTIC|BRIEF PSYCHOTIC|PSYCHOSIS|PSYCHOTIC", "MH05"),
    (r"SEVERE PNEUMONIA", "CD13"),
    (r"\bPNEUMONIA", "CD12"),
    (r"UPPER RESPIRATORY|ACUTE.*RESPIRATORY INFECT|COMMON COLD|\bCOLD\b", "CD11"),
    (r"\bASTHMA", "CR01"),
    (r"COPD|CHRONIC OBSTRUCTIVE", "CR02"),
    (r"BRONCHITIS|BRONCHIOLITIS|ALLERGIC AIRWAY", "CR03"),
    (r"PULPITIS|DENTAL CARIES|\bCARIES\b|TOOTH|RETAINED DENTAL", "OD01"),
    (r"GINGIVITIS", "OD02"),
    (r"URINARY TRACT INFECT|\bUTI\b|CYSTITIS|PYELONEPHRITIS", "CD07"),
    (r"PELVIC INFLAMMATOR", "CD17"),
    (r"INTESTINAL WORM|HELMINTH|ASCARIAS|HOOKWORM", "CD08"),
    (r"URETHRAL DISCHARGE", "CD03"),
    (r"GENITAL ULCER", "CD04"),
    (r"CHLAMYDIA|GONORRH|SYPHILIS|SEXUALLY TRANSMITTED|\bSTI\b", "CD06"),
    (r"ALLERGIC CONJUNCTIVITIS|ALLERGIC CONJUCTIVITIS", "EC01"),
    (r"BACTERIAL CONJUNCTIVITIS", "EC02"),
    (r"CONJUNCTIVITIS|CONJUCTIVITIS", "EC04_2019"),
    (r"CORNEAL ULCER|KERATITIS", "EC04"),
    (r"\bCATARACT", "EC05"),
    (r"REFRACTIVE ERROR|DISORDERS? (OF|DUE).*REFRACT|MYOPIA|HYPERMETROPIA|ASTIGMAT", "EC07"),
    (r"\bGLAUCOMA", "EC08"),
    (r"DRY EYE|PTERYGIUM|PINGUECULA|UVEITIS|EYE", "EC25_2019"),
    (r"MALARIA IN PREGNAN", "MC03"),
    (r"MALARIA DUE TO|CONFIRMED MALARIA|\bMALARIA\b", "EP01c"),
    (r"TYPHOID", "EP15"),
    (r"COVID", "EP18"),
    (r"DIARRHOEA|DIARRHEA|GASTRO ?ENTERITIS", "CD01"),
    (r"GASTRITIS|PEPTIC ULCER|GASTRO-?INTESTINAL|GORD|GASTRO-?OESOPHAGEAL|REFLUX", "NC03"),
    (r"HEPATITIS B", "LD07"),
    (r"HEPATITIS C", "LD08"),
    (r"\bSKIN\b|DERMATITIS|ECZEMA|TINEA|SCABIES|FUNGAL INFECTION", "CD14"),
    (r"SINUSITIS", "EN05"),
    (r"TONSILLITIS", "EN13"),
    (r"OTITIS MEDIA", "EN01"),
    (r"OTITIS EXTERNA", "EN10"),
    (r"IMPACTED CERUMEN|CERUMEN|EAR WAX", "EN17"),
    (r"RHINITIS", "EN04"),
    (r"PHARYNGITIS|SORE THROAT", "EN17"),
    (r"\bSTROKE|CEREBROVASCULAR|HEMIPLEGIA(?! DUE)", "CV01"),
    (r"HEART FAILURE|CARDIAC FAILURE", "CV03"),
    (r"HYPERTENSIVE HEART|ISCHEMIC HEART|ISCHAEMIC HEART", "CV04"),
    (r"PARKINSON", "NE03"),
    (r"ACUTE KIDNEY|KIDNEY INJURY|RENAL FAILURE", "RD01"),
    (r"ANIMAL BITE|DOG BITE|SUSPECTED RABIES", "IN04a"),
    (r"SNAKE BITE", "IN05"),
    (r"INSECT BITE", "IN06"),
    (r"LUMBAGO|LOW BACK PAIN|BACK PAIN|SCIATICA|RADICULOPATH|SPONDYL", "PT16"),
    (r"MYALGIA|MUSCLE (STRAIN|SPRAIN)|SOFT TISSUE|OSTEOARTHRIT|\bJOINT\b|ARTHRITIS", "PT02"),
    (r"CLUBFOOT|VENTRICULAR SEPTAL|CONGENITAL|BIRTH DEFECT", "PT15"),
    (r"HEMIPLEGIA|PARAPLEGIA|SPINAL CORD|PARALYSIS", "PT06"),
    (r"PERIPHERAL NEUROPATH|NEUROPATH|FACIAL NEURITIS|NEURITIS|FACIAL PALSY", "PT09"),
    (r"SUPERVISION OF NORMAL PREGNAN|NORMAL PREGNAN", "MC03"),
    (r"ANAEMIA COMPLICATING PREGNAN", "MC03"),
    (r"ANAEMIA|ANEMIA", "NC02_2019"),
    (r"BACTERAEMIA|SEPSIS|SEPTICAEMIA|SEPTICEMIA", "OP01"),
    (r"SUBSTANCE|PSYCHOACTIVE|DRUG USE|ALCOHOL USE", "MH17_2019"),
    (r"MIGRAINE|HEADACHE", "OP01"),
    (r"PROSTATE|HYPERPLASIA OF PROSTATE", "CA15"),
]

_POLICY = [(re.compile(p), c) for p, c in POLICY_RULES]
_EMR = [(re.compile(p), c) for p, c in EMR_RULES]


def _looks_like_code(token: str, code_index) -> bool:
    return re.sub(r"\s+", "", token) in code_index


_ICD11 = None


def icd11_map() -> dict:
    """ClinicMaster ICD-11 disease code -> HMIS 105 code.

    Generated by scripts/build_icd11_map.py from the hospital's own Diseases
    table, so it reflects what Jinja records rather than a textbook. A code
    absent from the table compiles to OP01 All others, which is a real HMIS line
    and an honest answer: the condition was seen and counted, but not against a
    line of its own.

    Missing file is not fatal. Everything falls to All others, the figures are
    incomplete rather than wrong, and that is the safer failure - the collision
    this table exists to prevent produced figures that were confidently wrong."""
    global _ICD11
    if _ICD11 is not None:
        return _ICD11
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), "icd11_hmis_map.json")
    try:
        with open(path) as fh:
            _ICD11 = json.load(fh).get("map", {})
    except (OSError, ValueError):
        _ICD11 = {}
    return _ICD11


def normalise_code(code: str) -> str:
    """One normal form for a ClinicMaster disease code, used when the table is
    BUILT and when it is READ.

    Both sides matter. The table was first built from the dictionary verbatim
    and read back upper-cased, so 'k8956' (Upper respiratory tract infection,
    123 cases in July 2026) and 'nr302' (Tinea pedis) never matched and were
    reported as All others. Jinja's dictionary carries fifteen lower-case codes
    and eighteen containing a space - 'DO 970' is vaginal candidiasis - because
    local codes are typed by hand alongside the real ICD-11 stems."""
    return re.sub(r"\s+", "", str(code or "")).upper()


def icd11_to_hmis(code: str):
    """The HMIS 105 code for a ClinicMaster disease code, or None."""
    key = normalise_code(code)
    return icd11_map().get(key) if key else None


def map_diagnosis(raw: str, code_index, source: str = "emr"):
    """Translate a raw diagnosis into an HMIS 105 code.

    `source` says which namespace `raw` belongs to, and it is not optional
    thinking. Read the warning below before changing it.

    - "emr":   free text, or an HMIS 105 code a records officer typed. An exact
               match against the HMIS index is honoured.
    - "icd11": a ClinicMaster Diseases.DiseaseCode. NEVER matched against the
               HMIS index by identity, because the two namespaces collide.

    Multi-diagnosis cells ('A, B') are split; the first segment that maps wins.
    Policy rules (HIV/TB) are checked first so they are handled deliberately.
    Unmapped-but-non-empty diagnoses return 'OP01' (All others). Empty input
    returns '' and the caller treats it as missing.

    ================================================================
    WHY `source` EXISTS: THE COLLISION OF 3 SEPTEMBER 2026
    ================================================================
    ICD-11 stems and HMIS 105 codes have the same shape - two letters and two
    digits - and they overlap. Until this was found, a ClinicMaster disease code
    was looked up directly in the HMIS index, and July 2026 compiled as:

        ClinicMaster DiseaseCode        reported to DHIS2 as
        CA01 Acute sinusitis        ->  105-CA01. Cervical Cancer
        CA02 Acute pharyngitis      ->  105-CA02. Prostate Cancer
        CA03 Acute tonsillitis      ->  105-CA03. Breast Cancer
        CA04 Acute laryngopharyngitis-> 105-CA04. Lung Cancer
        CA07 Acute URTI             ->  105-CA07. Colorectal Cancer
        NE10 Burns, multiple regions->  105-NE10. Child abuse and Neglect

    Thirty-three cancers and two child-protection cases, none of which existed.
    It surfaced only because the age and sex distribution was absurd - prostate
    cancer in a four-year-old girl, breast cancer in boys of five to nine. Had
    the colliding pairs been clinically plausible, this would have gone to the
    Ministry unnoticed and stayed in the national figures.

    The two namespaces cannot be told apart by looking at a code. Only the
    caller knows where its diagnoses came from, so only the caller can say.
    """
    if raw is None:
        return ""
    raw = str(raw).strip()
    if not raw:
        return ""

    # An ICD-11 code is never an HMIS code, however much it looks like one.
    allow_identity = source != "icd11"

    if allow_identity and _looks_like_code(raw, code_index):
        return re.sub(r"\s+", "", raw)

    if source == "icd11":
        mapped = icd11_to_hmis(raw)
        return mapped or "OP01"

    segments = [s.strip() for s in raw.split(",") if s.strip()] or [raw]
    for seg in segments:
        u = seg.upper()
        if _looks_like_code(seg, code_index):
            return re.sub(r"\s+", "", seg)
        for rx, code in _POLICY:
            if rx.search(u):
                return code
        for rx, code in _EMR:
            if rx.search(u):
                return code
    return "OP01"
