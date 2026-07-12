"""Report compilation — aggregates validated rows into DHIS2 data values.

OPD (HMIS 105:01):
  - OA01 New attendance / OA02 Re-attendance by OPD age band and sex
  - Each diagnosis code by OPD age band and sex

IPD (HMIS 108):
  - CI02 admissions, CI03 deaths, CI04 patient days by Ward Type
  - Section 6 diagnoses: Cases (<code>a) and Deaths (<code>b) by Age(0-4, 5+) and sex
"""
from collections import defaultdict
from datetime import date

from .validators import mapping, ipd_diagnosis_index

OPD_BANDS = [
    (28 / 365.0, "0-28Dys"),
    (5.0, "29Dys-4Yrs"),      # >28 days and under 5 years
    (10.0, "5-9Yrs"),
    (20.0, "10-19Yrs"),
    (999.0, "20+Yrs"),
]


def opd_band(age_years: float) -> str:
    for limit, label in OPD_BANDS:
        if age_years < limit or (label == "0-28Dys" and age_years <= limit):
            return label
    return "20+Yrs"


def ipd_band(age_years: float) -> str:
    return "0-4Yrs" if age_years < 5 else "5+Yrs"


def maternal_band(age_years: float) -> str:
    if age_years < 15:
        return "10-14Yrs"
    if age_years < 20:
        return "15-19Yrs"
    if age_years < 25:
        return "20-24Yrs"
    if age_years < 50:
        return "25-49Yrs"
    return "50+Yrs"


def neonatal_band(age_years: float):
    days = age_years * 365
    if days <= 7:
        return "0-7 days"
    if days <= 28:
        return "8-28 days"
    return None


def _coc(cc_key: str, name: str):
    return mapping()["categoryCombos"][cc_key]["cocs"].get(name)


def compile_opd(rows: list, period: str):
    m = mapping()
    code_index = m["HMIS105_01_codeIndex"]
    des = m["dataElements"]["HMIS105_01"]
    counts = defaultdict(int)
    unmapped = defaultdict(int)

    for r in rows:
        if not r.get("in_period"):
            continue
        band = opd_band(r["age_years"])
        coc_name = f"{band}, {r['sex']}"

        # attendance
        att_de = m["keyDataElements"]["OA01_newAttendance"] if r["visit_type"] == "New" \
            else m["keyDataElements"]["OA02_reAttendance"]
        counts[(att_de, _coc("OPD_AGE_SEX", coc_name))] += 1

        # diagnosis
        de_id = code_index.get(r["diagnosis_code"])
        if not de_id:
            unmapped[r["diagnosis_code"]] += 1
            continue
        cc = des[de_id]["categoryCombo"]
        if cc == m["categoryCombos"]["OPD_AGE_SEX"]["id"]:
            counts[(de_id, _coc("OPD_AGE_SEX", coc_name))] += 1
        elif cc == m["categoryCombos"]["DEFAULT"]["id"]:
            counts[(de_id, _coc("DEFAULT", "default"))] += 1
        else:
            unmapped[r["diagnosis_code"] + " (non-standard disaggregation)"] += 1

    return _to_values(counts, "HMIS105_01"), _unmapped_list(unmapped)


def compile_ipd(rows: list, period: str):
    m = mapping()
    code_index = m["HMIS108_codeIndex"]
    des = m["dataElements"]["HMIS108"]
    counts = defaultdict(int)
    unmapped = defaultdict(int)
    year, month = int(period[:4]), int(period[4:])

    ward_cc = m["categoryCombos"]["WARD_TYPE"]
    age_sex_cc = m["categoryCombos"]["IPD_AGE04_5P_SEX"]
    key = m["keyDataElements"]

    admissions = defaultdict(int)
    deaths_by_ward = defaultdict(int)
    patient_days = defaultdict(int)

    for r in rows:
        ward_coc = ward_cc["cocs"].get(r.get("ward") or "")
        adm = date.fromisoformat(r["admission_date"]) if r.get("admission_date") else None
        dis = date.fromisoformat(r["discharge_date"]) if r.get("discharge_date") else None

        if r.get("in_period") and ward_coc:
            admissions[ward_coc] += 1
        if r.get("outcome") == "Death" and ward_coc and (
            (dis and dis.year == year and dis.month == month) or (dis is None and r.get("in_period"))
        ):
            deaths_by_ward[ward_coc] += 1
        # patient days for stays concluded in the reporting month
        if adm and dis and dis.year == year and dis.month == month and ward_coc:
            patient_days[ward_coc] += max((dis - adm).days, 1)

        # Section 6 — admissions and deaths by diagnosis, age band and sex
        if r.get("in_period"):
            code = r["diagnosis_code"]
            pair = ipd_diagnosis_index().get(code, {})

            def coc_for(cc_id):
                if cc_id == age_sex_cc["id"]:
                    return age_sex_cc["cocs"].get(f"{ipd_band(r['age_years'])}, {r['sex']}")
                if cc_id == m["categoryCombos"]["IPD_AGE_SEX"]["id"]:
                    return m["categoryCombos"]["IPD_AGE_SEX"]["cocs"].get(maternal_band(r["age_years"]))
                if cc_id == m["categoryCombos"]["NEONATAL_AGE"]["id"]:
                    band = neonatal_band(r["age_years"])
                    return m["categoryCombos"]["NEONATAL_AGE"]["cocs"].get(band)
                return None

            recorded = False
            if pair.get("cases"):
                coc = coc_for(pair["cases_cc"])
                if coc:
                    counts[(pair["cases"], coc)] += 1
                    recorded = True
            if r.get("outcome") == "Death" and pair.get("deaths"):
                dcoc = coc_for(pair["deaths_cc"])
                if dcoc:
                    counts[(pair["deaths"], dcoc)] += 1
                    recorded = True
            if not recorded:
                reason = " (age outside disaggregation)" if pair else ""
                unmapped[code + reason] += 1

    for coc, n in admissions.items():
        counts[(key["CI02_admissions"], coc)] = n
    for coc, n in deaths_by_ward.items():
        counts[(key["CI03_deaths"], coc)] = n
    for coc, n in patient_days.items():
        counts[(key["CI04_patientDays"], coc)] = n
    # CI05 average length of stay = patient days / admissions (per ward)
    for coc, days in patient_days.items():
        if admissions.get(coc):
            counts[(key["CI05_avgLengthOfStay"], coc)] = round(days / admissions[coc], 1)

    return _to_values(counts, "HMIS108"), _unmapped_list(unmapped)


def _to_values(counts, dataset_key):
    m = mapping()
    des = m["dataElements"][dataset_key]
    coc_names = {}
    for cc in m["categoryCombos"].values():
        for name, cid in cc["cocs"].items():
            coc_names[cid] = name
    values = []
    for (de, coc), value in sorted(counts.items(), key=lambda kv: des[kv[0][0]]["name"]):
        if coc is None:
            continue
        values.append({
            "dataElement": de,
            "dataElementName": des[de]["name"],
            "categoryOptionCombo": coc,
            "categoryOptionComboName": coc_names.get(coc, coc),
            "value": str(value),
        })
    return values


def _unmapped_list(unmapped):
    return [{"code": k, "records": v} for k, v in sorted(unmapped.items())]
