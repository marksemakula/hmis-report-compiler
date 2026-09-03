"""Does every mapping point at a line the Ministry can actually see?

July 2026 was submitted three times before anyone asked that question. The
figures were right, the import reported success, and 1,174 of the month's
10,004 conditions - 11.7 per cent - were filed against nine elements that no
longer appear on the 105:01 form:

    PT09   311   Facial palsy              2019 physiotherapy section
    EC25_2019 255 Other Eye Disorders      superseded by EC25
    PT16   199   Spine disorders           2019 physiotherapy section
    EC04_2019 164 Other Forms of Conjunctivitis  code REUSED: EC04 is now
                                           Corneal Ulcers/Keratitis
    PT02   154   Joint dysfunction         2019 physiotherapy section
    PT15    53   Congenital abnormalities  2019 physiotherapy section
    MH17_2019 25 Substance use Disorder    code REUSED: MH17 is now PTSD
    NC02_2019 12 Other types of Anaemia    code REUSED: NC02 is now Other
                                           Haemoglobinopathies
    PT06     1   Paralysis                 2019 physiotherapy section

Those elements are still attached to the data set, so every write succeeded.
DHIS2 has no reason to object: the element exists, the value is valid, the
period is open. Only the form knows the row is gone.

Four of the nine are worse than a blank row. The current form reuses the code
for a different condition, so a reader comparing years sees conjunctivitis
counted as corneal ulcers and substance use counted as post-traumatic stress.

    python scripts/test_diagnosis.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import diagnosis_map as dm            # noqa: E402
from _lib.form_codes import FORM_CODES          # noqa: E402

FORM = set(FORM_CODES)
INDEX = {c: "de_" + c for c in FORM_CODES}      # membership is all mapping needs

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


def maps_to(name, code):
    check(f"{name[:44]} -> {code}", dm.map_diagnosis(name, INDEX, source="emr"), code)


print("\n-- every rule targets a line on the current form --")
off = sorted({c for _, c in dm.EMR_RULES if c not in FORM})
check("no EMR rule aims at a retired element", off, [])
off_policy = sorted({c for _, c in dm.POLICY_RULES if c not in FORM})
check("no policy rule aims at a retired element", off_policy, [])
off_retired = sorted({c for c in dm.RETIRED_TO_CURRENT.values() if c not in FORM})
check("every retired code is translated to one that exists", off_retired, [])
check("the form list is the 325 codes read from DHIS2", len(FORM), 325)

print("\n-- the generated ICD-11 table cannot reintroduce them --")
bad = sorted({v for v in dm.icd11_map().values() if v not in FORM})
check("no generated mapping aims at a retired element", bad, [])
check("the table is not empty", len(dm.icd11_map()) > 1500, True)

print("\n-- a retired code arriving from anywhere is translated --")
for old, new in sorted(dm.RETIRED_TO_CURRENT.items()):
    check(f"{old} -> {new}", dm.current_code(old), new)
# A records officer typing the code they learned in 2019, and a stale table.
check("typed into the DiagnosisCode column",
      dm.map_diagnosis("EC25_2019", {**INDEX, "EC25_2019": "de_old"}, source="emr"), "EC25")
check("a current code passes through untouched", dm.current_code("CV02"), "CV02")

print("\n-- the July 2026 conditions that had no home --")
# Every figure below is the count from the hospital's own July extract.
maps_to("ANTERIOR UVEITIS", "EC14")                       # 35, was EC25_2019
maps_to("PTERYGIUM", "EC25")                              # 60, was EC25_2019
maps_to("DRY EYE SYNDROME", "EC25")                       # 86, was EC25_2019
maps_to("PINGUECULAE", "EC25")                            # 43, was EC25_2019
maps_to("CONJUNCTIVITIS", "EC25")                         # 95, was EC04_2019
maps_to("BACTERIAL CONJUCTIVITIS", "EC02")                # 44, Jinja's own spelling
maps_to("BACTERIAL CONJUNCTIVITIS", "EC02")               # and the dictionary one
maps_to("HYPERTROPHY OF TONSILS WITH HYPERTROPHY OF ADENOIDS", "EN14")   # 31
maps_to("HYPERTROPHY OF ADENOIDS", "EN07")                # 22
maps_to("COUGH", "CD11")                                  # 19, was All others
maps_to("ALCOHOL USE DISORDER", "MH26")                   # was MH17_2019
maps_to("HARMFUL PATTERN OF USE OF PSYCHOACTIVE SUBSTANCE", "MH31")      # was MH17_2019

print("\n-- and the ones that genuinely have no line, which must say so --")
# The current form dropped the physiotherapy section outright. All others is
# the honest answer; a retired element is a hidden one.
maps_to("LUMBAGO WITH SCIATICA", "OP01")                  # 122
maps_to("PERIPHERAL NEUROPATHY", "OP01")                  # 163
maps_to("OSTEOARTHRITIS OF KNEE", "OP01")                 # 23
maps_to("MYALGIA", "OP01")                                # 24
maps_to("IRON DEFICIENCY ANAEMIA", "OP01")                # NC02 is not anaemia
maps_to("BACTERAEMIA", "OP01")                            # 138

print("\n-- conditions that already worked must not have moved --")
maps_to("ESSENTIAL HYPERTENSION", "CV02")
maps_to("TYPE 2 DIABETES MELLITUS", "EM01")
maps_to("SICKLE CELL DISEASE WITHOUT CRISIS", "NC01")
maps_to("EPILEPSY", "MH33")
maps_to("PULPITIS", "OD01")
maps_to("GASTRITIS", "NC03")
maps_to("SCHIZOPHRENIA", "MH07")
maps_to("BIPOLAR TYPE I DISORDER", "MH08")
maps_to("GENERALIZED ANXIETY DISORDER", "MH13")
maps_to("CORNEAL ULCER", "EC04")
maps_to("ALLERGIC CONJUNCTIVITIS", "EC01")
maps_to("TONSILLITIS", "EN13")
maps_to("IMPACTED CERUMEN", "EN17")
maps_to("HEPATITIS B", "LD07")
# The collision that started all of this: an ICD-11 stem is never an HMIS code.
check("an ICD-11 stem is not read as an HMIS code",
      dm.map_diagnosis("CA02", INDEX, source="icd11") == "CA02", False)

print(f"\n{len(failures)} failed")
for f in failures:
    print(" ", f)
sys.exit(1 if failures else 0)
