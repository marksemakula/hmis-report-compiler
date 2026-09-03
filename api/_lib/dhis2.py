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


def _same_number(a, b) -> bool:
    """'7' and '7.0' are the same figure. String equality first, because the
    values this app sends are already whole numbers written as text."""
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def stored_values(payload: dict, session=None) -> dict:
    """What the server holds right now for this data set, period and org unit,
    keyed (dataElement, categoryOptionCombo) -> value.

    Restricted to the attributeOptionCombo the payload was filed under: another
    attribute option is a different report about the same period."""
    s = session or _session()
    r = s.get(f"{base_url()}/api/dataValueSets.json",
              params={"dataSet": payload["dataSet"], "period": payload["period"],
                      "orgUnit": payload["orgUnit"]},
              timeout=60)
    r.raise_for_status()
    aoc = payload.get("attributeOptionCombo")
    held = {}
    for v in r.json().get("dataValues") or []:
        if aoc and v.get("attributeOptionCombo") not in (None, aoc):
            continue
        held[(v.get("dataElement"), v.get("categoryOptionCombo"))] = str(v.get("value", "")).strip()
    return held


def _names() -> tuple:
    """(data element id -> name, category option combo id -> name).

    A verification report that says 'LiSyn6bblsc is missing' tells the reader
    nothing; the same line naming Diarrhoea, 20+Yrs Female, can be acted on."""
    m = mapping()
    elements = {}
    for des in (m.get("dataElements") or {}).values():
        for deid, info in (des or {}).items():
            elements[deid] = (info or {}).get("name") or deid
    combos = {}
    for cc in (m.get("categoryCombos") or {}).values():
        for name, coc_id in ((cc or {}).get("cocs") or {}).items():
            combos[coc_id] = name
    return elements, combos


def verify_stored(payload: dict, session=None) -> dict:
    """Read the period back and compare it against what was sent.

    Import counts cannot answer the question a data manager actually has, which
    is whether the figures are on the server. DHIS2 counts a value it already
    holds unchanged as 'ignored', and by count alone that is indistinguishable
    from a value it declined to store.

    Measured on the live instance, 3 September 2026: July 2026 105:01 for Jinja
    was compiled to 325 values and submitted three times. The first wrote all
    322 it then contained. The second reported imported=3, updated=25,
    ignored=297. The third reported imported=0, updated=0, ignored=325, no
    conflicts, status SUCCESS - and reading the period back showed every one of
    the 325 on the server with the figure that had been sent. The app called
    that a failed submission. It was a report that had nothing left to say."""
    held = stored_values(payload, session=session)
    elements, combos = _names()
    matching, zeros_dropped, missing, differing = 0, 0, [], []
    for raw in payload.get("dataValues") or []:
        v = {**raw,
             "dataElementName": elements.get(raw.get("dataElement"), raw.get("dataElement")),
             "categoryOptionComboName": combos.get(raw.get("categoryOptionCombo"),
                                                   raw.get("categoryOptionCombo"))}
        sent_value = str(v.get("value", "")).strip()
        got = held.get((v.get("dataElement"), v.get("categoryOptionCombo")))
        if got is None:
            # A zero is not missing. zeroIsSignificant is false on 3,247 of the
            # 3,252 elements across these data sets, so the server keeps nothing
            # and the absent cell IS the zero.
            if sent_value == "0":
                zeros_dropped += 1
            else:
                missing.append(v)
        elif _same_number(got, sent_value):
            matching += 1
        else:
            differing.append({**v, "onServer": got})
    return {
        "checked": len(payload.get("dataValues") or []),
        "matching": matching,
        "zerosDropped": zeros_dropped,
        "missingCount": len(missing),
        "differingCount": len(differing),
        "missing": missing[:10],
        "differing": differing[:10],
        "unaccounted": len(missing) + len(differing),
    }


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
                description = summary.get("description", "")
                sent = len(payload.get("dataValues") or [])
                wrote = imported + updated
                zeros = sum(1 for v in (payload.get("dataValues") or [])
                            if str(v.get("value", "")).strip() == "0")
                status_ok = summary.get("status") in ("SUCCESS", "OK", "WARNING")

                # DHIS2 reports SUCCESS whatever the counts, so the old test for
                # success was imported + updated > 0. That test calls a report
                # with nothing left to change a failure: it writes nothing
                # because the server already holds every figure. When there is a
                # shortfall and no conflicts, ask the server what it holds
                # rather than inferring it from counts that cannot distinguish
                # "already correct" from "refused".
                verification, verify_failed = None, None
                if sent and wrote < sent and not conflicts:
                    try:
                        verification = verify_stored(payload, session=s)
                    except Exception as exc:     # noqa: BLE001
                        # The write has already happened by this point. A fault
                        # in the read-back is a lost diagnosis, never a lost
                        # submission, so it must not propagate. The type alone
                        # is recorded: an exception message can carry a URL or
                        # a token and this value is stored and displayed.
                        verification, verify_failed = None, type(exc).__name__
                reflected = bool(verification) and verification["unaccounted"] == 0
                accepted = status_ok and (wrote > 0 or reflected)

                if verification and reflected:
                    # The read-back cannot tell a value written a second ago
                    # from one that was already there, so the count DHIS2 gives
                    # for this import is what separates them.
                    already = max(verification["matching"] - wrote, 0)
                    parts = []
                    if imported and updated:
                        parts.append(f"{imported} written and {updated} updated just now")
                    elif imported:
                        parts.append(f"{imported} written just now")
                    elif updated:
                        parts.append(f"{updated} updated just now")
                    if already:
                        parts.append(f"{already} already held with the same figure")
                    if verification["zerosDropped"]:
                        parts.append(f"{verification['zerosDropped']} measured zero(s), "
                                     "which this instance does not store because an "
                                     "absent cell IS the zero")
                    description = (
                        f"All {sent} values are accounted for: " + "; ".join(parts) +
                        ". The period was read back from DHIS2 after submitting, so this "
                        "is what the national instance holds rather than an inference "
                        "from the import counts.")
                elif verification and verification["unaccounted"]:
                    description = (
                        f"DHIS2 reported no conflict, but reading the period back shows "
                        f"{verification['unaccounted']} of the {sent} values are not on the "
                        f"server: {verification['missingCount']} absent and "
                        f"{verification['differingCount']} holding a different figure. Check "
                        "that the data set is assigned to the org unit, the period is open, "
                        "and your user has data capture rights for it.")
                elif not accepted and sent:
                    # The read-back could not be made, so the counts are all
                    # there is to go on. Say so rather than diagnosing blind.
                    reasons = "; ".join(f"{c.get('object', '?')}: {c.get('value', '?')}"
                                        for c in conflicts[:5])
                    description = (
                        f"DHIS2 stored none of the {sent} values sent"
                        + (f" and ignored {ignored}" if ignored else "")
                        + ". "
                        + (f"Conflicts: {reasons}. " if reasons else "")
                        + (f"{zeros} of them were zeros, which this instance discards. "
                           if zeros else "")
                        + "The period could not be read back to check what the server "
                        + (f"holds ({verify_failed}), " if verify_failed else "holds, ")
                        + "so this may be a report with nothing left to change rather "
                          "than a rejection. Check that the data set is assigned to the "
                          "org unit, the period is open, and your user has data capture "
                          "rights for it.")
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
                    # Present only when the counts left a question to answer.
                    # Kept in the stored push response so a submission can be
                    # audited later without re-querying the national instance.
                    "verification": verification,
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
