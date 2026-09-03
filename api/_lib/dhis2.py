"""DHIS2 integration - authentication, metadata checks and dataValueSet submission."""
import os
import time
from datetime import date

import requests

from .validators import mapping


def base_url():
    return os.environ.get("DHIS2_BASE_URL", "https://hmis.health.go.ug").rstrip("/")


def dataset_key(report_type: str) -> str:
    """Resolve a report type to its data set key via the single table in metadata."""
    types = mapping().get("reportTypes", {})
    entry = types.get((report_type or "").upper())
    if not entry:
        raise RuntimeError(
            f"Unknown report type '{report_type}'. Check the report code in the "
            f"request; the registered reports are: {', '.join(sorted(types))}.")
    return entry["dataSet"]


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
    ds_id = m["dataSets"][dataset_key(report_type)]["id"]
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

    # 2. Is the data set assigned to this org unit? (filtered query - cheap even on a national instance)
    r = s.get(f"{b}/api/dataSets.json?filter=id:eq:{ds_id}&filter=organisationUnits.id:eq:{ou_id}&fields=id", timeout=30)
    r.raise_for_status()
    checks["dataSetAssignedToOrgUnit"] = len(r.json().get("dataSets", [])) > 0

    # 3. Does this account have data WRITE sharing on the data set (distinct from metadata access)?
    r = s.get(f"{b}/api/dataSets/{ds_id}.json?fields=id,name,periodType,expiryDays,openFuturePeriods,"
              f"access[data[read,write]],categoryCombo[id,name,isDefault,categoryOptionCombos[id,name]]", timeout=30)
    r.raise_for_status()
    ds = r.json()
    cc = ds.get("categoryCombo", {})
    checks["dataSet"] = {"name": ds.get("name"), "periodType": ds.get("periodType"),
                         "expiryDays": ds.get("expiryDays"), "openFuturePeriods": ds.get("openFuturePeriods"),
                         "attributeCategoryCombo": {k: cc.get(k) for k in ("id", "name", "isDefault")}}
    checks["dataWriteAccess"] = bool(ds.get("access", {}).get("data", {}).get("write"))
    if not cc.get("isDefault", True):
        checks["attributeOptionCombos"] = cc.get("categoryOptionCombos", [])
        try:
            checks["attributeOptionComboSelected"] = resolve_attribute_option_combo(ds_id, session=s)
        except RuntimeError as exc:
            checks["attributeOptionComboSelected"] = None
            checks["attributeOptionComboError"] = str(exc)

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


def resolve_attribute_option_combo(ds_id: str, session=None):
    """The Uganda HMIS data sets are attributed by a non-default category combo
    ('Nationality'). Values submitted without an attributeOptionCombo are filed
    under the default combo and silently ignored, so we must resolve the right one.

    Selection order: DHIS2_AOC env var (UID or name, e.g. 'National'), otherwise
    the sole option if only one exists, otherwise raise listing the choices."""
    s = session or _session()
    b = base_url()
    r = s.get(f"{b}/api/dataSets/{ds_id}.json?fields=categoryCombo[id,name,isDefault,"
              f"categoryOptionCombos[id,name]]", timeout=30)
    r.raise_for_status()
    cc = r.json().get("categoryCombo", {})
    if cc.get("isDefault", True):
        return None  # default combo - DHIS2 handles it implicitly
    options = cc.get("categoryOptionCombos", [])
    wanted = os.environ.get("DHIS2_AOC", "").strip()
    if wanted:
        def _norm(name):
            # tolerate numbering prefixes such as '1. National'
            import re
            return re.sub(r"^\s*\d+\s*[.)-]?\s*", "", name).strip().lower()
        for o in options:
            if o["id"] == wanted or _norm(o["name"]) == _norm(wanted):
                return o["id"]
        raise RuntimeError(
            f"DHIS2_AOC is set to '{wanted}', which this data set's "
            f"'{cc.get('name')}' combination does not offer. Set DHIS2_AOC in the "
            "project settings to one of: "
            + ", ".join(f"{o['name']} ({o['id']})" for o in options))
    if len(options) == 1:
        return options[0]["id"]
    raise RuntimeError(
        f"This data set is attributed by '{cc.get('name')}' and DHIS2 needs to know which option "
        f"this report belongs to. Set the DHIS2_AOC environment variable in Vercel to one of: "
        + ", ".join(f"{o['name']} ({o['id']})" for o in options))


def build_payload(report_type: str, period: str, data_values: list, org_unit: str = None):
    m = mapping()
    ds = m["dataSets"][dataset_key(report_type)]
    payload = {
        "dataSet": ds["id"],
        "completeDate": date.today().isoformat(),
        "period": period,
        "orgUnit": org_unit or m["orgUnit"]["id"],
        # Imputed zeros are a rendering device and must never be submitted.
        # They are added by coverage.zero_fill for the preview only, and are
        # never persisted, so in practice none reach here - this filter exists
        # so that a future caller who passes the displayed values by mistake
        # gets the right payload rather than a silent misreport.
        #
        # Sending them would in any case achieve nothing. Measured against the
        # live instance on 2 September 2026, a dry-run import of "1" reports
        # imported=1 and the identical element with "0" reports imported=0,
        # ignored=0 and no conflict: zeroIsSignificant is false on 3,247 of the
        # 3,252 elements across the eight data sets, so DHIS2 drops the zero
        # without comment. On the server, the absent cell IS the zero.
        "dataValues": [
            {
                "dataElement": v["dataElement"],
                "categoryOptionCombo": v["categoryOptionCombo"],
                "value": v["value"],
            }
            for v in data_values
            if not v.get("imputed")
        ],
    }
    aoc = resolve_attribute_option_combo(ds["id"])
    if aoc:
        payload["attributeOptionCombo"] = aoc
    return payload


def submit(payload: dict, max_retries: int = 3, dry_run: bool = False):
    """POST the dataValueSet with retry and exponential back-off.

    With dry_run, DHIS2 validates the payload and returns the identical import
    summary it would have produced, but writes nothing. Every conflict a real
    submission would raise - unknown element, closed period, missing capture
    right - surfaces exactly as it would, which makes this the safe way to
    exercise the whole path against the live national instance."""
    s = _session()
    url = f"{base_url()}/api/dataValueSets"
    if dry_run:
        url += "?dryRun=true"
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
                # 409 returns import summary with conflicts - surface it rather than retry
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
                sent = len(payload.get("dataValues") or [])
                zeros = sum(1 for v in (payload.get("dataValues") or [])
                            if str(v.get("value", "")).strip() == "0")

                if not accepted and sent:
                    reasons = "; ".join(f"{c.get('object', '?')}: {c.get('value', '?')}" for c in conflicts[:5])
                    if zeros == sent:
                        # Every value was a zero. This instance stores none of
                        # them, so nothing written is the CORRECT outcome rather
                        # than a failure, and saying "ignored" would be wrong -
                        # DHIS2 reports neither imported nor ignored for a
                        # discarded zero, which is how this looked like silence.
                        description = (
                            f"All {sent} values were zeros, and this instance does not store "
                            "them: zeroIsSignificant is false on almost every element, so an "
                            "absent cell IS the zero. Nothing was written, and nothing needed "
                            "to be. The figures remain correct on the form and in the preview.")
                    elif ignored > 0:
                        description = (
                            f"DHIS2 accepted the request but ignored all {ignored} value(s) - nothing was written. "
                            f"{('Conflicts: ' + reasons) if reasons else 'No conflict details returned; check that the data set is assigned to the org unit, the period is open, and your user has data capture rights for it.'}"
                        )
                    else:
                        description = (
                            f"DHIS2 stored none of the {sent} values sent and reported no "
                            "conflicts. "
                            + (f"{zeros} of them were zeros, which this instance discards. " if zeros else "")
                            + "Check that the data set is assigned to the org unit, the period "
                              "is open, and your user has data capture rights for it.")
                # A PARTIAL shortfall needs explaining too, and its commonest
                # cause is not an error at all. DHIS2 discards a zero for any
                # element with zeroIsSignificant false, which is 3,247 of the
                # 3,252 elements across these eight data sets. Week 35 of 2026
                # compiles eleven 033B values of which five are genuine measured
                # zeros, so DHIS2 keeps six and the app would otherwise report
                # a shortfall with no reason given.
                if accepted and sent and (imported + updated) < sent and not description:
                    kept = imported + updated
                    description = f"DHIS2 stored {kept} of the {sent} values sent."
                    if zeros:
                        description += (
                            f" {zeros} of them were zeros, which this instance does not "
                            "store: zeroIsSignificant is false on almost every element, so "
                            "an absent cell IS the zero. A measured zero is still correct "
                            "on the form and in the preview; it simply has nothing to "
                            "write on the server.")
                    elif conflicts:
                        description += " See the conflicts below."

                return {
                    "httpStatus": r.status_code,
                    "status": summary.get("status", "UNKNOWN"),
                    "accepted": accepted,
                    "importCount": counts,
                    "valuesSent": sent,
                    "zerosSent": zeros,
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
