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


def preflight(report_type: str = "OPD", org_unit: str = None):
    """Diagnose why a submission might be silently ignored: checks identity,
    data set assignment to the org unit, data write access, capture scope and expiry rules."""
    m = mapping()
    ds_key = "HMIS105_01" if report_type == "OPD" else "HMIS108"
    ds_id = m["dataSets"][ds_key]["id"]
    ou_id = org_unit or m["orgUnit"]["id"]
    s = _session()
    b = base_url()
    checks = {}

    # 1. Who does DHIS2 think we are, and which org units can we capture data for?
    me = s.get(f"{b}/api/me.json?fields=id,username,authorities,organisationUnits[id,name,level]", timeout=30)
    me.raise_for_status()
    me = me.json()
    capture_ous = me.get("organisationUnits", [])
    checks["identity"] = {"username": me.get("username"), "captureOrgUnits": capture_ous}
    auths = set(me.get("authorities", []))
    checks["canAddDataValues"] = "ALL" in auths or "F_DATAVALUE_ADD" in auths

    # 2. Is the data set assigned to this org unit? (filtered query — cheap even on a national instance)
    r = s.get(f"{b}/api/dataSets.json?filter=id:eq:{ds_id}&filter=organisationUnits.id:eq:{ou_id}&fields=id", timeout=30)
    r.raise_for_status()
    checks["dataSetAssignedToOrgUnit"] = len(r.json().get("dataSets", [])) > 0

    # 3. Does this account have data WRITE sharing on the data set (distinct from metadata access)?
    r = s.get(f"{b}/api/dataSets/{ds_id}.json?fields=id,name,periodType,expiryDays,openFuturePeriods,"
              f"access[data[read,write]],categoryCombo[id,name,isDefault]", timeout=30)
    r.raise_for_status()
    ds = r.json()
    checks["dataSet"] = {"name": ds.get("name"), "periodType": ds.get("periodType"),
                         "expiryDays": ds.get("expiryDays"), "openFuturePeriods": ds.get("openFuturePeriods"),
                         "attributeCategoryCombo": ds.get("categoryCombo")}
    checks["dataWriteAccess"] = bool(ds.get("access", {}).get("data", {}).get("write"))

    # 4. Is the target org unit inside the account's capture hierarchy?
    r = s.get(f"{b}/api/organisationUnits/{ou_id}.json?fields=id,name,path", timeout=30)
    r.raise_for_status()
    ou = r.json()
    path_ids = set(ou.get("path", "").strip("/").split("/"))
    checks["orgUnit"] = {"id": ou.get("id"), "name": ou.get("name")}
    checks["orgUnitInCaptureScope"] = any(c["id"] in path_ids or c["id"] == ou_id for c in capture_ous)

    checks["ok"] = all([checks["canAddDataValues"], checks["dataSetAssignedToOrgUnit"],
                        checks["dataWriteAccess"], checks["orgUnitInCaptureScope"]])
    return checks


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
