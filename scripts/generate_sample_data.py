"""Generates realistic sample OPD and IPD files for testing the compiler."""
import csv
import random
import sys
from datetime import date, timedelta

random.seed(42)

YEAR, MONTH = 2026, 6
DAYS = 30

OPD_CODES = ["EP01a", "EP01c", "CD01", "CD02", "EP05", "EP07", "EP15", "MH26", "NC03", "OD01",
             "EN01", "EC01", "EP13", "NC04", "EN13"]
IPD_CODES = ["ME06a", "NC09", "MC10", "CD01", "ND05", "RD01", "NT08"]
WARDS = ["Male Medical", "Female Medical", "Paediatrics", "Maternity", "Male Surgical",
         "Female Surgical", "Emergency", "ICU", "Neonatal", "Gynaecology"]


def rand_age():
    r = random.random()
    if r < 0.08:
        return random.randint(1, 28), "Days"
    if r < 0.35:
        return random.randint(1, 4), "Years"
    if r < 0.5:
        return random.randint(5, 9), "Years"
    if r < 0.65:
        return random.randint(10, 19), "Years"
    return random.randint(20, 90), "Years"


def opd(path, n=2000):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["PatientNo", "VisitDate", "Age", "AgeUnit", "Sex", "DiagnosisCode", "VisitType"])
        for i in range(1, n + 1):
            age, unit = rand_age()
            d = date(YEAR, MONTH, random.randint(1, DAYS))
            w.writerow([
                f"JRRH/OPD/{i:05d}", d.isoformat(), age, unit,
                random.choice(["M", "F"]), random.choice(OPD_CODES),
                "New" if random.random() < 0.8 else "Re-attendance",
            ])
    print("wrote", path)


def ipd(path, n=600):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["PatientNo", "AdmissionDate", "DischargeDate", "Age", "AgeUnit", "Sex",
                    "Ward", "DiagnosisCode", "Outcome"])
        for i in range(1, n + 1):
            age, unit = rand_age()
            adm = date(YEAR, MONTH, random.randint(1, DAYS))
            stay = random.randint(1, 14)
            dis = adm + timedelta(days=stay)
            discharged = dis.month == MONTH and dis.year == YEAR
            outcome = "Death" if random.random() < 0.05 else ("Discharged" if discharged else "")
            w.writerow([
                f"JRRH/IPD/{i:05d}", adm.isoformat(),
                dis.isoformat() if discharged else "",
                age, unit, random.choice(["M", "F"]),
                random.choice(WARDS), random.choice(IPD_CODES), outcome,
            ])
    print("wrote", path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    opd(f"{out}/sample_opd_202606.csv")
    ipd(f"{out}/sample_ipd_202606.csv")
