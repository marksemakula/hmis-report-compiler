"""Ingestion: parsing and validation of OPD (105) and IPD (108) upload files."""
import csv
import io
import re
from datetime import datetime, date

from .metadata import mapping
from .diagnosis_map import map_diagnosis


_IPD_INDEX = None


def ipd_diagnosis_index():
    """Pairs HMIS 108 Section-6 'Cases'/'Deaths' data elements under user-friendly keys.

    Accepts e.g. 'CD01' (from CD01a/CD01b), 'CV01a' (from CV01a1/CV01a2),
    the exact DE code, and legacy '_2019' variants.
    """
    global _IPD_INDEX
    if _IPD_INDEX is not None:
        return _IPD_INDEX
    m = mapping()
    supported_ccs = {
        m["categoryCombos"]["IPD_AGE04_5P_SEX"]["id"],   # Age(0-4, 5+Yrs) & Sex
        m["categoryCombos"]["IPD_AGE_SEX"]["id"],        # maternal age bands
        m["categoryCombos"]["NEONATAL_AGE"]["id"],       # Age(0-7, 8-28 days)
    }
    index = {}

    def add(key, kind, deid, cc, legacy):
        if not key:
            return
        entry = index.setdefault(key, {})
        # prefer current codes over legacy _2019 variants
        if kind in entry and not entry.get(kind + "_legacy", True) and legacy:
            return
        entry[kind] = deid
        entry[kind + "_cc"] = cc
        entry[kind + "_legacy"] = legacy

    for deid, info in m["dataElements"]["HMIS108"].items():
        cc, code, name = info["categoryCombo"], info["code"], info["name"]
        if cc not in supported_ccs or not code:
            continue
        legacy = code.endswith("_2019")
        if re.search(r"-\s*Cases\s*$", name):
            add(code, "cases", deid, cc, legacy)
            add(re.sub(r"a(_2019)?$", "", code), "cases", deid, cc, legacy)
            add(re.sub(r"([a-d])1(_2019)?$", r"\1", code), "cases", deid, cc, legacy)
        elif re.search(r"-\s*Deaths\s*$", name):
            add(code, "deaths", deid, cc, legacy)
            add(re.sub(r"b(_2019)?$", "", code), "deaths", deid, cc, legacy)
            add(re.sub(r"([a-d])2(_2019)?$", r"\1", code), "deaths", deid, cc, legacy)
    _IPD_INDEX = index
    return index


OPD_COLUMNS = ["PatientNo", "VisitDate", "Age", "AgeUnit", "Sex", "DiagnosisCode", "VisitType"]
IPD_COLUMNS = ["PatientNo", "AdmissionDate", "DischargeDate", "Age", "AgeUnit", "Sex",
               "Ward", "DiagnosisCode", "Outcome"]

SEX_VALUES = {"M": "Male", "MALE": "Male", "F": "Female", "FEMALE": "Female"}
VISIT_TYPES = {"NEW": "New", "RE-ATTENDANCE": "Re", "REATTENDANCE": "Re", "RE": "Re", "RETURN": "Re"}
OUTCOMES = {"DISCHARGE", "DISCHARGED", "DEATH", "DIED", "REFERRED", "ABSCONDED", "TRANSFERRED", ""}
AGE_UNITS = {"YEARS", "YRS", "Y", "MONTHS", "M", "DAYS", "D", ""}

# Aliases from common ward names to the DHIS2 Ward Type category options
WARD_ALIASES = {
    "male medical": "MaleMedical", "malemedical": "MaleMedical",
    "female medical": "FemaleMedical", "femalemedical": "FemaleMedical",
    "male surgical": "MaleSurgical", "malesurgical": "MaleSurgical",
    "female surgical": "FemaleSurgical", "femalesurgical": "FemaleSurgical",
    "paediatric": "Paediatrics", "paediatrics": "Paediatrics", "pediatrics": "Paediatrics", "children": "Paediatrics",
    "maternity": "Maternity_Obstetric", "obstetric": "Maternity_Obstetric", "maternity_obstetric": "Maternity_Obstetric",
    "gynaecology": "Gynaecology", "gynecology": "Gynaecology", "gyn": "Gynaecology",
    "emergency": "Emergency Ward", "emergency ward": "Emergency Ward", "a&e": "Emergency Ward", "casualty": "Emergency Ward",
    "icu": "Intensive Care Unit (ICU)", "intensive care": "Intensive Care Unit (ICU)", "intensive care unit": "Intensive Care Unit (ICU)", "intensive care unit (icu)": "Intensive Care Unit (ICU)",
    "neonatal": "Neonatal Unit", "neonatal unit": "Neonatal Unit", "nicu": "Neonatal Unit",
    "tb": "TB", "tuberculosis": "TB",
    "psychiatric": "Psychiatric", "psychiatry": "Psychiatric", "mental health": "Psychiatric",
    "eye": "Eye", "ophthalmology": "Eye",
    "ent": "ENT",
    "orthopaedic": "Orthopaedic", "orthopedic": "Orthopaedic", "ortho": "Orthopaedic",
    "nutrition": "Nutrition",
    "palliative": "Palliative",
    "rehabilitation": "Rehabilitation Ward", "rehabilitation ward": "Rehabilitation Ward", "rehab": "Rehabilitation Ward",
    "acute care": "AcuteCareUnit", "acute care unit": "AcuteCareUnit", "acutecareunit": "AcuteCareUnit",
    "other": "Other wards", "other wards": "Other wards",
}


def normalise_ward(value: str):
    return WARD_ALIASES.get(str(value).strip().lower())


def _parse_date(value):
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    # Excel serial number
    try:
        serial = float(value)
        if 20000 < serial < 60000:
            return date(1899, 12, 30) + __import__("datetime").timedelta(days=int(serial))
    except ValueError:
        pass
    return None


def age_in_years(age, unit):
    try:
        age = float(age)
    except (TypeError, ValueError):
        return None
    unit = str(unit or "years").strip().upper()
    if unit.startswith("D"):
        return age / 365.0
    if unit.startswith("M") and unit != "MALE":
        return age / 12.0
    return age


def _row_is_blank(values) -> bool:
    return all(v is None or str(v).strip() == "" for v in values)


def _pick_sheet(wb, expected_columns):
    """Choose the worksheet whose header row best matches the expected columns.

    Guards against workbooks where the active sheet is empty or unrelated
    (e.g. an export whose first sheet holds only formatting).
    """
    best, best_hits = None, 0
    for ws in wb.worksheets:
        first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if not first:
            continue
        header = {str(c).strip() for c in first if c is not None}
        hits = len(header & set(expected_columns))
        if hits > best_hits:
            best, best_hits = ws, hits
    return best if best is not None and best_hits >= 3 else None


def parse_file(filename: str, content: bytes, expected_columns=None):
    """Return list of row dicts from CSV or Excel content.

    Blank rows (all cells empty) are skipped: Excel files often carry
    thousands of formatted-but-empty ghost rows after data is deleted,
    which would otherwise all fail validation.
    """
    if filename.lower().endswith((".xlsx", ".xls", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = (_pick_sheet(wb, expected_columns) if expected_columns else None) or wb.active
        rows = [r for r in ws.iter_rows(values_only=True) if not _row_is_blank(r)]
        if not rows:
            return []
        header = [str(c).strip() if c is not None else "" for c in rows[0]]
        return [dict(zip(header, [("" if c is None else str(c)) for c in r])) for r in rows[1:]]
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader if not _row_is_blank(r.values())]


def validate_rows(report_type: str, rows: list, period: str):
    """Validate parsed rows. Returns (clean_rows, errors)."""
    m = mapping()
    code_index = m["HMIS105_01_codeIndex"] if report_type == "OPD" else m["HMIS108_codeIndex"]
    year, month = int(period[:4]), int(period[4:])
    errors, clean = [], []

    required = ["PatientNo", "Age", "Sex", "DiagnosisCode"] + (
        ["VisitDate", "VisitType"] if report_type == "OPD" else ["AdmissionDate", "Ward"]
    )

    for i, row in enumerate(rows, start=2):  # header is line 1
        row = {str(k).strip(): str(v).strip() for k, v in row.items() if k}
        problems = []

        for field in required:
            if not row.get(field):
                problems.append(f"{field} is required")

        sex = SEX_VALUES.get(row.get("Sex", "").upper())
        if row.get("Sex") and not sex:
            problems.append(f"Sex '{row.get('Sex')}' is not recognised (use M or F)")

        years = age_in_years(row.get("Age"), row.get("AgeUnit"))
        if row.get("Age") and years is None:
            problems.append(f"Age '{row.get('Age')}' is not a valid number")
        if years is not None and not (0 <= years <= 130):
            problems.append(f"Age {years:.1f} years is outside the acceptable range")

        raw_code = row.get("DiagnosisCode", "").strip()
        # Translate EMR free-text diagnosis names into HMIS 105 codes.
        # Already-valid codes pass through unchanged.
        code = map_diagnosis(raw_code, code_index) if (report_type == "OPD" and raw_code) else raw_code
        code_norm = re.sub(r"\s+", "", code)
        if code and report_type == "OPD" and code_norm not in code_index:
            problems.append(f"Diagnosis code '{code}' does not match any HMIS 105 data element")
        if code and report_type == "IPD":
            if code_norm not in ipd_diagnosis_index():
                problems.append(f"Diagnosis code '{code}' does not match any HMIS 108 Cases/Deaths data element")

        if report_type == "OPD":
            d = _parse_date(row.get("VisitDate", ""))
            if row.get("VisitDate") and d is None:
                problems.append(f"VisitDate '{row.get('VisitDate')}' is not a valid date")
            in_period = d is not None and d.year == year and d.month == month
            vt = VISIT_TYPES.get(row.get("VisitType", "").upper())
            if row.get("VisitType") and not vt:
                problems.append(f"VisitType '{row.get('VisitType')}' must be New or Re-attendance")
            parsed = {"visit_date": d.isoformat() if d else None, "visit_type": vt}
        else:
            adm = _parse_date(row.get("AdmissionDate", ""))
            dis = _parse_date(row.get("DischargeDate", "")) if row.get("DischargeDate") else None
            if row.get("AdmissionDate") and adm is None:
                problems.append(f"AdmissionDate '{row.get('AdmissionDate')}' is not a valid date")
            if row.get("DischargeDate") and dis is None:
                problems.append(f"DischargeDate '{row.get('DischargeDate')}' is not a valid date")
            if adm and dis and dis < adm:
                problems.append("DischargeDate is earlier than AdmissionDate")
            ward = normalise_ward(row.get("Ward", "")) if row.get("Ward") else None
            if row.get("Ward") and ward is None:
                problems.append(f"Ward '{row.get('Ward')}' is not recognised")
            outcome = row.get("Outcome", "").upper()
            if outcome and outcome not in OUTCOMES:
                problems.append(f"Outcome '{row.get('Outcome')}' is not recognised")
            in_period = adm is not None and adm.year == year and adm.month == month
            parsed = {
                "admission_date": adm.isoformat() if adm else None,
                "discharge_date": dis.isoformat() if dis else None,
                "ward": ward,
                "outcome": "Death" if outcome in ("DEATH", "DIED") else (outcome.title() or None),
            }

        if problems:
            errors.append({"line": i, "patient": row.get("PatientNo", ""), "problems": problems})
        else:
            clean.append({
                **row, **parsed,
                "sex": sex, "age_years": years,
                "diagnosis_code": code_norm,
                "in_period": in_period,
            })
    return clean, errors
