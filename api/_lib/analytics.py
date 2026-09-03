"""Figures above the facility: Busoga region and the national total.

Everything else in this application is about one hospital. The compiler reads
this hospital's registers, the `reports` table holds what this hospital
compiled, and `orgUnit` in metadata.py is a single identifier. None of that can
answer "how is the region doing", because the region's data was never here - it
is in DHIS2, written by four hundred other facilities.

So the two wider scopes are read from the DHIS2 **analytics** API rather than
computed locally, and they are a genuinely different kind of number. At facility
scope the dashboard counts *our own compilation workflow* - what we compiled,
what we submitted, what failed. Above the facility that workflow does not exist;
what exists is whether each facility's report arrived at all. The two must not
be presented as the same measure, and the endpoint labels them separately.

Three things are worth knowing before changing this file.

**Analytics is not dataValueSets.** dhis2.py reads raw values for one org unit
and one period, which is what verification after a submission needs. Analytics
aggregates down a hierarchy and is the only practical way to ask about four
hundred facilities at once. It is also served from precomputed tables, so a
period whose analytics run has not happened yet reads as missing rather than
zero - see `stale` in the payload.

**Reporting rates are data elements with a suffix.** DHIS2 exposes
`{dataSetUid}.REPORTING_RATE`, `.ACTUAL_REPORTS`, `.EXPECTED_REPORTS` and the
two on-time variants as ordinary `dx` items. There is no separate endpoint.

**A period belongs to a cadence.** Asking for a weekly data set's reporting rate
over a monthly period silently aggregates five weeks into one figure and reads
as a rate above 100. The data sets are therefore grouped by periodType and each
group is asked with its own period.
"""
import os
import time

from .metadata import mapping
from . import periods

# Analytics answers for a closed period do not change between requests, and a
# serverless container may serve several in a row. Sixty seconds is enough to
# stop a tab switch re-querying four hundred facilities, and short enough that
# a metadata fix shows up while someone is still looking at the page.
_CACHE = {}
_CACHE_TTL = 60.0

# Uganda's hierarchy on hmis.health.go.ug is national / region / district /
# subcounty / facility-parent / facility, with the hospital at level 6. Both
# are overridable because a level number is exactly the sort of thing that
# differs between instances and must not require a code change.
REGION_LEVEL = int(os.environ.get("DHIS2_REGION_LEVEL", "2"))

SCOPES = ("facility", "region", "national")


def _session(session=None):
    """The caller's session, or a credentialed one from dhis2.py.

    Imported inside the function, not at module scope. dhis2.py pulls in
    validators, which pulls in the diagnosis map and the compiler; importing it
    at the top would mean this module could not be exercised without the whole
    compilation stack present. Every test passes its own session, so that
    import never happens offline.
    """
    if session is not None:
        return session
    from . import dhis2
    return dhis2._session()


def _base():
    """The instance URL, read the same way metadata.py reads it - the embedded
    constant is the default and the environment overrides it. Deliberately not
    dhis2.base_url(), for the import reason above."""
    from .metadata import CONSTANTS
    return os.environ.get("DHIS2_BASE_URL", CONSTANTS["instance"]).rstrip("/")


def _cached(key, produce):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    value = produce()
    _CACHE[key] = (time.time(), value)
    return value


def reset_cache():
    """Drop memoised analytics. Called by the admin metadata refresh."""
    _CACHE.clear()


# --------------------------------------------------------------- hierarchy

def hierarchy(session=None) -> dict:
    """The three org units the dashboard can be scoped to.

    Resolved from the facility's own ancestors rather than hard-coded, so the
    region follows if the Ministry re-parents the hospital. `DHIS2_REGION_OU`
    and `DHIS2_NATIONAL_OU` override the lookup entirely for an instance whose
    levels are arranged differently.
    """
    def produce():
        m = mapping()
        facility = dict(m["orgUnit"])
        facility["scope"] = "facility"

        s = _session(session)
        r = s.get(f"{_base()}/api/organisationUnits/{facility['id']}.json",
                  params={"fields": "id,name,level,path,ancestors[id,name,level]"},
                  timeout=30)
        if r.status_code == 404:
            raise RuntimeError(
                f"The configured organisation unit {facility['id']} does not exist on "
                f"{_base()}. Check `orgUnit` in api/_lib/metadata.py against the instance.")
        r.raise_for_status()
        ou = r.json()
        ancestors = ou.get("ancestors") or []

        by_level = {a.get("level"): a for a in ancestors if a.get("level")}

        national_id = os.environ.get("DHIS2_NATIONAL_OU", "")
        national = ({"id": national_id, "name": "Ministry of Health - National", "level": 1}
                    if national_id else by_level.get(1))

        region_id = os.environ.get("DHIS2_REGION_OU", "")
        region = ({"id": region_id, "name": "Region", "level": REGION_LEVEL}
                  if region_id else by_level.get(REGION_LEVEL))

        # An ancestor list that does not reach the expected level means the
        # hierarchy is shaped differently, not that the request failed. Say so
        # in words the operator can act on rather than returning half a payload.
        if not national:
            raise RuntimeError(
                "The national organisation unit could not be resolved: "
                f"{facility['name']} reports no level-1 ancestor. Set DHIS2_NATIONAL_OU "
                "to the root organisation unit's UID.")
        if not region:
            raise RuntimeError(
                f"The regional organisation unit could not be resolved: {facility['name']} "
                f"has no ancestor at level {REGION_LEVEL}. Set DHIS2_REGION_OU to the "
                "region's UID, or DHIS2_REGION_LEVEL to the level regions sit at.")

        return {
            "facility": {**facility, "scope": "facility"},
            "region": {**region, "scope": "region"},
            "national": {**national, "scope": "national"},
            "facilityLevel": ou.get("level") or facility.get("level") or 6,
        }

    return _cached("hierarchy", produce)


def scopes(session=None) -> list:
    """The tab list: the three scopes, facility first."""
    h = hierarchy(session=session)
    return [
        {"scope": "facility", "id": h["facility"]["id"], "name": h["facility"]["name"],
         "short": "Jinja RRH", "level": h["facility"].get("level"), "source": "local"},
        {"scope": "region", "id": h["region"]["id"], "name": h["region"]["name"],
         "short": h["region"]["name"], "level": h["region"].get("level"), "source": "dhis2"},
        {"scope": "national", "id": h["national"]["id"], "name": h["national"]["name"],
         "short": "MoH - National", "level": h["national"].get("level"), "source": "dhis2"},
    ]


# --------------------------------------------------------------- analytics

def _rows(payload) -> list:
    """Analytics rows as dicts.

    The row is a bare array whose meaning comes from `headers`; zipping against
    the header names rather than assuming dx/pe/ou/value order is what keeps
    this working when a dimension is added or the order changes.
    """
    names = [h.get("name") for h in payload.get("headers", [])]
    return [dict(zip(names, row)) for row in payload.get("rows", [])]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def query(dx, ou, pe, session=None, extra=None) -> dict:
    """One analytics request. Returns {'rows': [...], 'names': {uid: name}}."""
    dx = [d for d in (dx or []) if d]
    if not dx:
        return {"rows": [], "names": {}}
    params = {
        "dimension": [f"dx:{';'.join(dx)}", f"pe:{pe}", f"ou:{ou}"],
        "skipMeta": "false",
        "displayProperty": "NAME",
    }
    if extra:
        params.update(extra)

    s = _session(session)
    r = s.get(f"{_base()}/api/analytics.json", params=params, timeout=60)
    if r.status_code in (401, 403):
        raise RuntimeError(
            f"DHIS2 refused the analytics request for organisation unit {ou} "
            f"({r.status_code}). The account can submit for this hospital but may not hold "
            "data-read sharing above it. Set DHIS2_USERNAME and DHIS2_PASSWORD (or "
            "DHIS2_PAT) to an account with read access at regional and national level, and "
            "check the sharing settings on those organisation units in DHIS2.")
    r.raise_for_status()
    payload = r.json()
    names = {k: v.get("name") for k, v in (payload.get("metaData", {})
                                           .get("items", {}) or {}).items()}
    return {"rows": _rows(payload), "names": names}


# ------------------------------------------------------- reporting completeness

_RATE_METRICS = ("REPORTING_RATE", "ACTUAL_REPORTS", "EXPECTED_REPORTS",
                 "ACTUAL_REPORTS_ON_TIME", "REPORTING_RATE_ON_TIME")


def _by_cadence() -> dict:
    """Report types grouped by the period type they are collected on."""
    m = mapping()
    groups = {}
    for key, entry in m.get("reportTypes", {}).items():
        ds = m["dataSets"].get(entry["dataSet"])
        if not ds:
            continue
        groups.setdefault(entry["periodType"], []).append({
            "type": key,
            "short": entry["short"],
            "label": entry["label"],
            "dataSet": ds["id"],
            "periodType": entry["periodType"],
        })
    return groups


def completeness(ou: str, session=None) -> list:
    """Per data set: how many facilities under `ou` reported, and how many were
    expected. One request per cadence, each asked with its own period."""
    out = []
    for period_type, entries in sorted(_by_cadence().items()):
        period = periods.default_period(period_type)
        dx = [f"{e['dataSet']}.{metric}" for e in entries for metric in _RATE_METRICS]
        res = query(dx, ou, period, session=session)

        values = {}
        for row in res["rows"]:
            values[row.get("dx")] = _num(row.get("value"))

        for e in entries:
            rate = values.get(f"{e['dataSet']}.REPORTING_RATE")
            actual = values.get(f"{e['dataSet']}.ACTUAL_REPORTS")
            expected = values.get(f"{e['dataSet']}.EXPECTED_REPORTS")
            on_time = values.get(f"{e['dataSet']}.ACTUAL_REPORTS_ON_TIME")
            out.append({
                **e,
                "period": period,
                "periodLabel": periods.describe(period_type, period),
                "reportingRate": rate,
                "actual": int(actual) if actual is not None else None,
                "expected": int(expected) if expected is not None else None,
                "onTime": int(on_time) if on_time is not None else None,
                "onTimeRate": values.get(f"{e['dataSet']}.REPORTING_RATE_ON_TIME"),
                # Analytics returns nothing at all for a period it has not run
                # yet. That is not the same as "no facility reported", and
                # showing it as 0% would libel four hundred facilities.
                "stale": rate is None and actual is None,
            })
    out.sort(key=lambda e: (e["periodType"], e["short"]))
    return out


def trend(ou: str, session=None, months: int = 12) -> list:
    """Reporting rate for the monthly data sets over the last `months` periods."""
    monthly = _by_cadence().get("Monthly", [])
    if not monthly:
        return []
    dx = [f"{e['dataSet']}.REPORTING_RATE" for e in monthly]
    res = query(dx, ou, f"LAST_{months}_MONTHS", session=session)

    buckets = {}
    for row in res["rows"]:
        pe = row.get("pe")
        v = _num(row.get("value"))
        if pe is None or v is None:
            continue
        buckets.setdefault(pe, []).append(v)

    out = []
    for pe in sorted(buckets):
        vals = buckets[pe]
        out.append({
            "period": pe,
            "label": periods.describe("Monthly", pe),
            "rate": round(sum(vals) / len(vals), 1),
        })
    return out


def indicators(ou: str, session=None) -> list:
    """Headline totals - OPD attendance, admissions, deaths, patient days.

    The identifiers come from `keyDataElements` in metadata.py, which is the
    same table the compiler writes against, so a figure shown here and a figure
    submitted from here are the same element and cannot drift.
    """
    m = mapping()
    keys = m.get("keyDataElements", {})
    wanted = [
        ("OA01_newAttendance", "OPD new attendance", "105:01"),
        ("OA02_reAttendance", "OPD re-attendance", "105:01"),
        ("CI02_admissions", "Admissions", "108"),
        ("CI03_deaths", "Deaths", "108"),
        ("CI04_patientDays", "Patient days", "108"),
    ]
    dx = [keys[k] for k, _, _ in wanted if keys.get(k)]
    if not dx:
        return []

    period = periods.default_period("Monthly")
    res = query(dx, ou, period, session=session)
    totals = {}
    for row in res["rows"]:
        v = _num(row.get("value"))
        if v is not None:
            totals[row.get("dx")] = totals.get(row.get("dx"), 0) + v

    out = []
    for key, label, source in wanted:
        uid = keys.get(key)
        if not uid:
            continue
        out.append({
            "label": label,
            "source": source,
            "value": int(totals[uid]) if uid in totals else None,
            "period": period,
            "periodLabel": periods.describe("Monthly", period),
        })
    return out


def ranking(session=None, report_type: str = "OPD") -> dict:
    """Where this hospital sits among the facilities of its region.

    Ranked on one data set's reporting rate rather than an average across
    eight, because an average over data sets a facility is not assigned would
    rank facilities on how many forms they are expected to file. 105:01 is the
    monthly outpatient return every facility in the region submits.
    """
    h = hierarchy(session=session)
    m = mapping()
    entry = m.get("reportTypes", {}).get(report_type.upper())
    if not entry:
        return {}
    ds = m["dataSets"][entry["dataSet"]]
    period = periods.default_period(entry["periodType"])
    level = h["facilityLevel"]

    res = query([f"{ds['id']}.REPORTING_RATE"],
                f"LEVEL-{level};{h['region']['id']}", period, session=session)

    peers = []
    for row in res["rows"]:
        v = _num(row.get("value"))
        ou_id = row.get("ou")
        if v is None or not ou_id:
            continue
        peers.append({"id": ou_id, "name": res["names"].get(ou_id, ou_id), "rate": round(v, 1)})

    if not peers:
        return {"period": period, "periodLabel": periods.describe(entry["periodType"], period),
                "dataSet": entry["short"], "of": 0, "rank": None, "stale": True, "top": []}

    # Descending by rate; ties share the better rank, which is what a person
    # means by "joint third" and what a dense ranking gives.
    peers.sort(key=lambda p: -p["rate"])
    rank = None
    seen = 0
    last = None
    for i, p in enumerate(peers):
        if p["rate"] != last:
            seen = i + 1
            last = p["rate"]
        p["rank"] = seen
        if p["id"] == h["facility"]["id"]:
            rank = seen

    return {
        "period": period,
        "periodLabel": periods.describe(entry["periodType"], period),
        "dataSet": entry["short"],
        "of": len(peers),
        "rank": rank,
        "stale": False,
        "facility": next((p for p in peers if p["id"] == h["facility"]["id"]), None),
        "top": peers[:5],
    }


# ------------------------------------------------------------------ overview

def overview(scope: str, session=None) -> dict:
    """Everything one scope's tab needs, in one request."""
    scope = (scope or "").lower()
    if scope not in SCOPES:
        raise RuntimeError(
            f"Unknown scope '{scope}'. Check the scope parameter on the request; "
            f"the dashboard scopes are: {', '.join(SCOPES)}.")

    h = hierarchy(session=session)
    ou = h[scope]
    sets = completeness(ou["id"], session=session)

    reported = [e for e in sets if not e["stale"]]
    expected_total = sum(e["expected"] or 0 for e in reported)
    actual_total = sum(e["actual"] or 0 for e in reported)
    on_time_total = sum(e["onTime"] or 0 for e in reported)

    tiles = [
        {"label": "Data sets tracked", "value": len(sets),
         "foot": f"{len(reported)} with figures for the current period", "tone": "primary"},
        {"label": "Reports received", "value": actual_total,
         "foot": f"of {expected_total:,} expected" if expected_total else "Nothing expected yet",
         "tone": "success"},
        {"label": "Reporting rate",
         "value": round(100 * actual_total / expected_total, 1) if expected_total else None,
         "unit": "%", "foot": "Facilities that filed, over those assigned", "tone": "azure"},
        {"label": "Filed on time",
         "value": round(100 * on_time_total / actual_total, 1) if actual_total else None,
         "unit": "%", "foot": f"{on_time_total:,} of {actual_total:,} received", "tone": "warning"},
    ]

    out = {
        "scope": scope,
        "orgUnit": {"id": ou["id"], "name": ou["name"], "level": ou.get("level")},
        "tiles": tiles,
        "dataSets": sets,
        "trend": trend(ou["id"], session=session),
        "indicators": indicators(ou["id"], session=session),
        "source": "DHIS2 analytics",
    }
    # Ranking is a statement about this hospital's place among its peers, so it
    # belongs on the region tab and is meaningless on the facility's own.
    if scope in ("region", "national"):
        out["ranking"] = ranking(session=session)
    return out
