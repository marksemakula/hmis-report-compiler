"""DHIS2 integration — authentication, metadata checks and dataValueSet submission."""
import os
import time
from datetime import date

import requests

from .validators import mapping


def base_url():
    return os.environ.get("DHIS2_BASE_URL", "https://hmis.health.go.ug").rstrip("/")


def _session():
    s = requests.Session()
    pat = os.environ.get("DHIS2_PAT", "")
    if pat:
        s.headers["Authorization"] = f"ApiToken {pat}"
    else:
        user = os.environ.get("DHIS2_USERNAME", "")
        pwd = os.environ.get("DHIS2_PASSWORD", "")
        if not user or not pwd:
            raise RuntimeError(
                "DHIS2 credentials are not configured. Set DHIS2_USERNAME and DHIS2_PASSWORD "
                "(or DHIS2_PAT) in the Vercel project settings."
            )
        s.auth = (user, pwd)
    s.headers["Accept"] = "application/json"
    return s


def test_connection():
    s = _session()
    r = s.get(f"{base_url()}/api/me.json?fields=id,username,organisationUnits[id,name]", timeout=30)
    r.raise_for_status()
    return r.json()


def build_payload(report_type: str, period: str, data_values: list, org_unit: str = None):
    m = mapping()
    ds = m["dataSets"]["HMIS105_01" if report_type == "OPD" else "HMIS108"]
    return {
        "dataSet": ds["id"],
        "completeDate": date.today().isoformat(),
        "period": period,
        "orgUnit": org_unit or m["orgUnit"]["id"],
        "dataValues": [
            {
                "dataElement": v["dataElement"],
                "categoryOptionCombo": v["categoryOptionCombo"],
                "value": v["value"],
            }
            for v in data_values
        ],
    }


def submit(payload: dict, max_retries: int = 3):
    """POST the dataValueSet with retry and exponential back-off."""
    s = _session()
    url = f"{base_url()}/api/dataValueSets"
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            r = s.post(url, json=payload, timeout=120)
            body = {}
            try:
                body = r.json()
            except ValueError:
                body = {"raw": r.text[:2000]}
            if r.status_code in (200, 201, 409):
                # 409 returns import summary with conflicts — surface it rather than retry
                summary = body.get("response", body)
                counts = summary.get("importCount", {})
                imported = int(counts.get("imported", 0) or 0)
                updated = int(counts.get("updated", 0) or 0)
                ignored = int(counts.get("ignored", 0) or 0)
                conflicts = summary.get("conflicts", [])[:50]
                # DHIS2 reports status SUCCESS even when every value is ignored,
                # so success must be judged on the import counts, not the status flag.
                accepted = summary.get("status") in ("SUCCESS", "OK", "WARNING") and (imported + updated) > 0
                description = summary.get("description", "")
                if not accepted and ignored > 0:
                    reasons = "; ".join(f"{c.get('object', '?')}: {c.get('value', '?')}" for c in conflicts[:5])
                    description = (
                        f"DHIS2 accepted the request but ignored all {ignored} value(s) — nothing was written. "
                        f"{('Conflicts: ' + reasons) if reasons else 'No conflict details returned; check that the data set is assigned to the org unit, the period is open, and your user has data capture rights for it.'}"
                    )
                return {
                    "httpStatus": r.status_code,
                    "status": summary.get("status", "UNKNOWN"),
                    "accepted": accepted,
                    "importCount": counts,
                    "conflicts": conflicts,
                    "description": description,
                }
            if r.status_code in (401, 403):
                return {"httpStatus": r.status_code, "status": "ERROR",
                        "description": "DHIS2 rejected the credentials or the user lacks permission for this data set."}
            last_error = f"HTTP {r.status_code}: {str(body)[:500]}"
        except requests.RequestException as exc:
            last_error = str(exc)
        if attempt < max_retries:
            time.sleep(2 ** attempt)
    return {"httpStatus": 0, "status": "ERROR", "description": f"Submission failed after {max_retries} attempts: {last_error}"}
