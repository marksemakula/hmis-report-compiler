"""DHIS2 metadata.

Small, stable identifiers (data sets, organisation unit, category option combos)
were extracted from the live national instance and are embedded below.
The full data element listings (~1,500 elements) are fetched from the DHIS2 API
on first use and cached in Postgres. A local dhis2_mapping.json (used in
development) takes precedence when present.
"""
import json
import os

CONSTANTS = {
    "instance": "https://hmis.health.go.ug",
    "orgUnit": {"id": "SZS6IdnTKZR", "name": "Jinja Regional Referral Hospital", "level": 6},
    "dataSets": {
        "HMIS105_01": {"id": "RtEYsASU7PG", "name": "HMIS 105:01 - OPD Monthly Report (Attendance, Referrals, Conditions, TB, Nutrition)", "periodType": "Monthly"},
        "HMIS108": {"id": "EBqVAQRmiPm", "name": "HMIS 108 - IPD Monthly Report", "periodType": "Monthly"},
    },
    "keyDataElements": {
        "OA01_newAttendance": "sv6SeKroHPV",
        "OA02_reAttendance": "sQ4EexvvhVe",
        "CI01_beds": "R9l3TcJpS5I",
        "CI02_admissions": "UwnR5kr982Y",
        "CI03_deaths": "vyOajQA5xTu",
        "CI04_patientDays": "zeWfiZxvpyo",
        "CI05_avgLengthOfStay": "dfaUCTHQIo8",
    },
    "categoryCombos": {
        "OPD_AGE_SEX": {"id": "esaNB4G5AHs", "name": "OPD Age(0-28days+) & Sex", "cocs": {
            "0-28Dys, Male": "zh2zAaHyYQx", "0-28Dys, Female": "wDiX34aiw6i",
            "29Dys-4Yrs, Male": "V2OuNTRI6ua", "29Dys-4Yrs, Female": "huBy3W5qiD2",
            "5-9Yrs, Male": "F1rms8f9I9a", "5-9Yrs, Female": "Crc5reUlspd",
            "10-19Yrs, Male": "c7gvocRdg0f", "10-19Yrs, Female": "u3CkZqMHfHP",
            "20+Yrs, Male": "dCKzhhINakS", "20+Yrs, Female": "XVHTeecEOM3",
        }},
        "IPD_AGE04_5P_SEX": {"id": "RQsR5eSRbsr", "name": "Age(0-4, 5+Yrs) & Sex", "cocs": {
            "0-4Yrs, Male": "rCzvys285kN", "0-4Yrs, Female": "VZrxjCi8cQi",
            "5+Yrs, Male": "ZgnHXnu30cI", "5+Yrs, Female": "fHgwVjoElmE",
        }},
        "IPD_AGE_SEX": {"id": "DYOKx6cUuRU", "name": "IPD Age & Sex", "cocs": {
            "10-14Yrs": "Kq56swi3KAi", "15-19Yrs": "oVc5PtW8IsH", "20-24Yrs": "dqUlEsSUs8w",
            "25-49Yrs": "xgiuSKF9lKY", "50+Yrs": "WQ8FzlyAWIM",
        }},
        "NEONATAL_AGE": {"id": "inJYzcJ1fUO", "name": "Age(0-7 days, 8-28 days)", "cocs": {
            "0-7 days": "q7cFI8zjhAp", "8-28 days": "UGTbjOrSMsh",
        }},
        "WARD_TYPE": {"id": "OX7MQfvWtye", "name": "Ward Type", "cocs": {
            "MaleMedical": "XJatc66P7A6", "FemaleMedical": "rj8MoomuB9C",
            "MaleSurgical": "u77V67JXHpb", "FemaleSurgical": "Agwj0d0hsc5",
            "Paediatrics": "lm5yShJh32E", "Maternity_Obstetric": "U3H71QfQ3EM",
            "Gynaecology": "dvlThSdHovb", "Emergency Ward": "vBmPAWZQDVs",
            "Intensive Care Unit (ICU)": "xg4v26gsfy0", "Neonatal Unit": "LqXPAf6aXaj",
            "TB": "CHqKEyZAHxD", "Psychiatric": "ToY1RNX7epJ", "Eye": "sQZH5BgucFf",
            "ENT": "vUgKzac3JnH", "Orthopaedic": "rJw5ESKTTCI", "Nutrition": "ObYelhgHfKG",
            "Palliative": "LPATiUAUj1c", "Rehabilitation Ward": "cskjOuUM9Ej",
            "AcuteCareUnit": "QE0t2SWaRky", "Other wards": "S55CGFRkdpq",
        }},
        "DEFAULT": {"id": "bjDvmb4bfuf", "name": "default", "cocs": {"default": "HllvX50cXC0"}},
    },
}

_MAPPING = None


def _build_code_index(des: dict) -> dict:
    idx = {}
    for deid, info in des.items():
        if info.get("code"):
            idx.setdefault(info["code"], []).append(deid)
    return {c: v[0] for c, v in idx.items() if len(v) == 1}


def _fetch_data_elements():
    """Fetch data element listings for both data sets from the DHIS2 API."""
    import re
    import requests

    user = os.environ.get("DHIS2_USERNAME", "")
    pwd = os.environ.get("DHIS2_PASSWORD", "")
    pat = os.environ.get("DHIS2_PAT", "")
    base = os.environ.get("DHIS2_BASE_URL", CONSTANTS["instance"]).rstrip("/")
    s = requests.Session()
    if pat:
        s.headers["Authorization"] = f"ApiToken {pat}"
    elif user and pwd:
        s.auth = (user, pwd)
    else:
        raise RuntimeError(
            "DHIS2 metadata is not cached yet and no DHIS2 credentials are configured. "
            "Set DHIS2_USERNAME and DHIS2_PASSWORD (or DHIS2_PAT) in the Vercel project settings."
        )
    out = {}
    for key, ds in CONSTANTS["dataSets"].items():
        r = s.get(
            f"{base}/api/dataSets/{ds['id']}.json",
            params={"fields": "id,name,dataSetElements[dataElement[id,name,categoryCombo[id]]]"},
            timeout=60,
        )
        r.raise_for_status()
        des = {}
        for e in r.json().get("dataSetElements", []):
            de = e["dataElement"]
            m = re.match(r"^(105|108)-([A-Za-z0-9_]+)[\.\s]\s*(.*)$", de["name"])
            des[de["id"]] = {
                "name": de["name"],
                "code": m.group(2) if m else None,
                "categoryCombo": de["categoryCombo"]["id"],
            }
        out[key] = des
    return out


def _load_from_db():
    from . import db
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS metadata_cache (
                key VARCHAR(64) PRIMARY KEY, value JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            cur.execute("SELECT value FROM metadata_cache WHERE key='data_elements'")
            row = cur.fetchone()
            return row["value"] if row else None


def _save_to_db(value):
    from . import db
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO metadata_cache (key, value) VALUES ('data_elements', %s)
                   ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()""",
                (json.dumps(value),),
            )


def mapping(force_refresh: bool = False):
    """Return the full mapping: constants + data element listings + code indices."""
    global _MAPPING
    if _MAPPING is not None and not force_refresh:
        return _MAPPING

    des = None
    # 1. local development file
    local = os.path.join(os.path.dirname(__file__), "dhis2_mapping.json")
    if not force_refresh and os.path.exists(local):
        with open(local) as f:
            des = json.load(f)["dataElements"]
    # 2. database cache
    if des is None and not force_refresh:
        try:
            des = _load_from_db()
        except Exception:
            des = None
    # 3. live fetch
    if des is None:
        des = _fetch_data_elements()
        try:
            _save_to_db(des)
        except Exception:
            pass

    m = dict(CONSTANTS)
    m["dataElements"] = des
    m["HMIS105_01_codeIndex"] = _build_code_index(des["HMIS105_01"])
    m["HMIS108_codeIndex"] = _build_code_index(des["HMIS108"])
    _MAPPING = m
    return m
