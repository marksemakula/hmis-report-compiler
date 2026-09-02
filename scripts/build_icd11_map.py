"""Generate the ICD-11 to HMIS 105 mapping from ClinicMaster's own dictionary.

    python scripts/build_icd11_map.py path/to/09_diseases_exportResults.xlsx

WHY THIS IS GENERATED RATHER THAN WRITTEN

ClinicMaster records diagnoses as ICD-11 stem codes. HMIS 105 has its own codes.
They have the same shape - two letters, two digits - and they overlap, so until
3 September 2026 a ClinicMaster code was looked up directly in the HMIS index
and July compiled acute pharyngitis as prostate cancer. See map_diagnosis for
the full list of what that produced.

The fix needs a real translation table for 18,036 disease codes. Rather than
invent one, this derives it from the hospital's own dictionary: every disease
NAME is put through the curated clinical rules in diagnosis_map.EMR_RULES, and
the resulting code-to-element pairs are written out. That gives a mapping
grounded in what Jinja actually records, reviewable line by line, and
regenerable whenever the dictionary changes.

Codes that match no rule are deliberately absent. They compile to OP01 "All
others", which is a real HMIS 105 line and an honest answer: the condition was
seen and counted, but not against a line of its own.
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import diagnosis_map as dm  # noqa: E402

OUT = os.path.join(HERE, "..", "api", "_lib", "icd11_hmis_map.json")


def classify(name: str):
    """The HMIS 105 code a disease name implies, or None."""
    upper = (name or "").strip().upper()
    if not upper:
        return None
    for rx, code in dm._POLICY:
        if rx.search(upper):
            return code
    for rx, code in dm._EMR:
        if rx.search(upper):
            return code
    return None


def main(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    header = [str(c or "").strip() for c in rows[0]]
    if header[:2] != ["DiseaseCode", "DiseaseName"]:
        raise SystemExit(f"Unexpected columns {header[:2]}; expected "
                         "DiseaseCode, DiseaseName from 09_diseases_export.sql")

    mapping, skipped, collisions = {}, 0, {}
    for row in rows[1:]:
        code = str(row[0] or "").strip()
        name = str(row[1] or "").strip()
        if not code or not name:
            continue
        hmis = classify(name)
        if not hmis or hmis == "OP01":
            skipped += 1
            continue
        if code in mapping and mapping[code] != hmis:
            collisions[code] = (mapping[code], hmis)
        mapping[code] = hmis

    payload = {
        "_generated_from": os.path.basename(path),
        "_source": "ClinicMasterMOH.dbo.Diseases, exported by scripts/sql/09_diseases_export.sql",
        "_method": "disease NAME matched against diagnosis_map.EMR_RULES",
        "_codes_mapped": len(mapping),
        "_codes_to_all_others": skipped,
        "map": dict(sorted(mapping.items())),
    }
    with open(OUT, "w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=False)

    print(f"wrote {OUT}")
    print(f"  {len(mapping)} ICD-11 codes mapped to {len(set(mapping.values()))} HMIS elements")
    print(f"  {skipped} codes left to OP01 All others")
    if collisions:
        print(f"  {len(collisions)} duplicate codes disagreed; last wins:")
        for c, (a, b) in list(collisions.items())[:10]:
            print(f"    {c}: {a} then {b}")
    print()
    for code, n in Counter(mapping.values()).most_common(12):
        print(f"  {code:12s} {n:5d} codes")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
