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
import json
import os
import re
import time
from datetime import date, timedelta

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

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]

# District boundaries change when the Ministry creates a district, which is a
# handful of times a decade. They are also the largest thing this module
# returns, so they get their own long-lived cache rather than the 60 seconds
# the figures use.
_GEO_CACHE = {}
_GEO_TTL = 3600.0

# Four decimal places is about 11 metres at the equator - far finer than a
# district boundary drawn at this scale needs, and it roughly halves the
# payload, which matters on a hospital connection.
_COORD_DP = 4


def district_level() -> int:
    """Districts sit one level below regions. Overridable for an instance whose
    hierarchy is arranged differently."""
    override = os.environ.get("DHIS2_DISTRICT_LEVEL", "")
    return int(override) if override else REGION_LEVEL + 1


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
    _GEO_CACHE.clear()


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
            # Which district this hospital sits in, so the map can mark it.
            # Absent rather than guessed if the hierarchy is shaped otherwise.
            "district": by_level.get(district_level()),
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


def query(dx, ou, pe, session=None, extra=None, co=False) -> dict:
    """One analytics request. Returns {'rows': [...], 'names': {uid: name}}.

    `co` adds the category option combo as a dimension, which is how a total is
    broken out by its disaggregation - age band and sex, for the OPD elements.
    Without it analytics returns the element already summed across every combo.
    """
    dx = [d for d in (dx or []) if d]
    if not dx:
        return {"rows": [], "names": {}}
    dims = [f"dx:{';'.join(dx)}", f"pe:{pe}", f"ou:{ou}"]
    if co:
        dims.append("co")
    params = {
        "dimension": dims,
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


# ---------------------------------------------------------------- the map
#
# The district outlines come from DHIS2, not from a shapefile checked in here.
# Every organisation unit can carry a `geometry` property, and the Ministry's
# instance already has them - that is the only reason the DHIS2 Maps app can
# draw Busoga at all. Reading them from the same place as the figures means the
# shapes and the numbers share organisation unit identifiers and cannot drift,
# and a district created next year appears without anyone re-exporting a file.


def _round_ring(ring):
    # A GeoJSON position is [lon, lat] but may legally carry a third element
    # for altitude. Unpacking as `for x, y in ring` raises on those, which the
    # caller would have swallowed as "no geometry" - a district silently
    # missing from the map is the worst way for this to fail, so take the
    # first two ordinates and ignore any others.
    return [[round(float(p[0]), _COORD_DP), round(float(p[1]), _COORD_DP)] for p in ring]


def _normalise_geometry(geo):
    """A Polygon or MultiPolygon as nested coordinate rings, or None.

    Points are skipped: a facility carries one, and a dot cannot be shaded.
    """
    # DHIS2 before 2.36 stored `featureType` plus a `coordinates` JSON string
    # rather than a GeoJSON `geometry` object. Reshaping it here means an older
    # instance draws a map instead of an empty card.
    if isinstance(geo, str):
        try:
            geo = {"type": "MultiPolygon", "coordinates": json.loads(geo)}
        except (TypeError, ValueError):
            return None
    if not isinstance(geo, dict):
        return None
    kind = geo.get("type")
    coords = geo.get("coordinates")
    if not coords:
        return None
    try:
        if kind == "Polygon":
            return {"type": "Polygon", "coordinates": [_round_ring(r) for r in coords]}
        if kind == "MultiPolygon":
            return {"type": "MultiPolygon",
                    "coordinates": [[_round_ring(r) for r in poly] for poly in coords]}
    except (TypeError, ValueError):
        return None
    return None


def _bbox(shapes):
    xs, ys = [], []
    for s in shapes:
        rings = s["coordinates"] if s["type"] == "Polygon" else \
            [r for poly in s["coordinates"] for r in poly]
        for ring in rings:
            for x, y in ring:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def districts(session=None) -> dict:
    """The region's districts with their outlines, for the choropleth."""
    def produce():
        h = hierarchy(session=session)
        s = _session(session)
        r = s.get(f"{_base()}/api/organisationUnits.json",
                  params={"filter": f"parent.id:eq:{h['region']['id']}",
                          "fields": "id,name,level,geometry",
                          "paging": "false"},
                  timeout=60)
        if r.status_code in (401, 403):
            raise RuntimeError(
                f"DHIS2 refused the organisation unit listing for {h['region']['name']} "
                f"({r.status_code}). Set DHIS2_USERNAME and DHIS2_PASSWORD (or DHIS2_PAT) "
                "to an account that can read the region's districts, and check the sharing "
                "settings on those organisation units in DHIS2.")
        r.raise_for_status()

        out = []
        without = []
        for ou in r.json().get("organisationUnits", []):
            raw = ou.get("geometry")
            if raw is None and ou.get("coordinates"):
                raw = ou["coordinates"]          # pre-2.36 shape
            geo = _normalise_geometry(raw)
            if geo is None:
                # "No boundary in DHIS2" and "has a location but no area" are
                # different facts. Only the first is worth telling the reader:
                # a Point belongs to a facility, is not a district that failed
                # to get an outline, and listing it as one would send someone
                # looking for a boundary that was never meant to exist.
                if not isinstance(raw, dict) or not raw.get("coordinates"):
                    without.append(ou.get("name") or ou.get("id"))
                continue
            out.append({"id": ou["id"], "name": ou.get("name"), "geometry": geo})
        out.sort(key=lambda d: (d["name"] or "").lower())

        return {
            "region": {"id": h["region"]["id"], "name": h["region"]["name"]},
            "facilityDistrict": (h.get("district") or {}).get("id"),
            "districts": out,
            "bbox": _bbox([d["geometry"] for d in out]),
            # Named rather than silently omitted: a district with no boundary
            # in DHIS2 is missing from the map, and the reader should be told
            # which one rather than left counting shapes.
            "withoutGeometry": sorted(without),
        }

    hit = _GEO_CACHE.get("districts")
    if hit and time.time() - hit[0] < _GEO_TTL:
        return hit[1]
    value = produce()
    _GEO_CACHE["districts"] = (time.time(), value)
    return value


def recent_periods(period_type: str, count: int = 12) -> list:
    """The last `count` closed periods of a cadence, newest first."""
    pt = (period_type or "Monthly").capitalize()
    today = date.today()
    out = []
    if pt == "Weekly":
        d = today - timedelta(days=7)
        for _ in range(count):
            out.append(periods.week_period(d))
            d -= timedelta(days=7)
    elif pt == "Quarterly":
        q = (today.month - 1) // 3 + 1
        year = today.year
        for _ in range(count):
            q -= 1
            if q == 0:
                q, year = 4, year - 1
            out.append(f"{year}Q{q}")
    else:
        year, month = today.year, today.month
        for _ in range(count):
            month -= 1
            if month == 0:
                month, year = 12, year - 1
            out.append(f"{year}{month:02d}")
    return [{"period": p, "label": periods.describe(pt, p)} for p in out]


# The five headline elements, in the order a person reads them.
_VOLUME = [
    ("OA01_newAttendance", "OPD new attendance"),
    ("OA02_reAttendance", "OPD re-attendance"),
    ("CI02_admissions", "Admissions"),
    ("CI03_deaths", "Deaths"),
    ("CI04_patientDays", "Patient days"),
]

_CASE_NAME = re.compile(r"\bcases?\b", re.I)
# '033B-CD01a. Cholera Cases' -> 'Cholera Cases'. Same prefix shapes metadata.py
# already handles, including the elements that omit the full stop.
_CODE_PREFIX = re.compile(r"^(105[A-Ca-c]?|106[Aa]|108|033[Bb])-[A-Za-z0-9_]+[\.\s]\s*")


def map_indicators() -> list:
    """What the map can be coloured by, grouped for a picker.

    Built from the registry rather than a second list of its own. The
    surveillance group in particular is derived from whatever 033B elements the
    metadata cache holds: this application has already been bitten once by
    mappings aimed at elements the Ministry had retired, and inventing disease
    names here would be the same mistake. A cache with no 033B listing yields
    no surveillance group at all, which is honest and self-correcting - an
    admin metadata refresh fills it in.
    """
    m = mapping()
    rates, ontime = [], []
    for entry in sorted(m.get("reportTypes", {}).values(), key=lambda e: e["short"]):
        ds = m["dataSets"].get(entry["dataSet"])
        if not ds:
            continue
        rates.append({"id": f"rate:{ds['id']}", "label": f"{entry['short']} reporting rate",
                      "unit": "%", "kind": "percent", "periodType": entry["periodType"]})
        ontime.append({"id": f"ontime:{ds['id']}", "label": f"{entry['short']} on-time rate",
                       "unit": "%", "kind": "percent", "periodType": entry["periodType"]})

    keys = m.get("keyDataElements", {})
    volume = [{"id": f"de:{keys[k]}", "label": label, "unit": "", "kind": "count",
               "periodType": "Monthly"}
              for k, label in _VOLUME if keys.get(k)]

    surveillance = []
    for deid, info in (m.get("dataElements", {}).get("HMIS033B") or {}).items():
        name = (info or {}).get("name") or ""
        if not _CASE_NAME.search(name):
            continue
        surveillance.append({"id": f"de:{deid}",
                             "label": _CODE_PREFIX.sub("", name).strip() or name,
                             "unit": "", "kind": "count", "periodType": "Weekly"})
    surveillance.sort(key=lambda i: i["label"].lower())

    groups = [{"group": "Reporting rate", "items": rates},
              {"group": "On-time filing", "items": ontime}]
    if volume:
        groups.append({"group": "Service volume", "items": volume})
    if surveillance:
        groups.append({"group": "Surveillance cases", "items": surveillance})
    return groups


def _resolve_indicator(indicator: str):
    """'rate:<uid>' / 'ontime:<uid>' / 'de:<uid>' -> the analytics dx item."""
    kind, _, uid = (indicator or "").partition(":")
    if not uid or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{10}", uid):
        raise RuntimeError(
            f"Unrecognised map indicator '{indicator}'. Check the indicator parameter; "
            "it must be one of the ids returned by /api/py/map/indicators.")
    if kind == "rate":
        return f"{uid}.REPORTING_RATE", "percent", "%"
    if kind == "ontime":
        return f"{uid}.REPORTING_RATE_ON_TIME", "percent", "%"
    if kind == "de":
        return uid, "count", ""
    raise RuntimeError(
        f"Unrecognised map indicator '{indicator}'. Check the indicator parameter; "
        "the prefix must be rate, ontime or de.")


def map_values(indicator: str, period: str, session=None) -> dict:
    """One value per district, for one indicator and one period."""
    if not re.fullmatch(r"\d{4}(\d{2}|W\d{1,2}|Q[1-4])", str(period or "").upper()):
        raise RuntimeError(
            f"Unrecognised period '{period}'. Check the period parameter; it must be "
            "YYYYMM, YYYYWnn or YYYYQn.")
    dx, kind, unit = _resolve_indicator(indicator)
    h = hierarchy(session=session)
    res = query([dx], f"LEVEL-{district_level()};{h['region']['id']}",
                str(period).upper(), session=session)

    values = {}
    for row in res["rows"]:
        v = _num(row.get("value"))
        if v is None:
            continue
        # Analytics can return one row per (dx, ou); summing is a no-op for a
        # single dx and correct if a future caller passes more than one.
        values[row.get("ou")] = values.get(row.get("ou"), 0) + v

    numbers = sorted(values.values())
    return {
        "indicator": indicator,
        "period": str(period).upper(),
        "kind": kind,
        "unit": unit,
        "values": values,
        "min": numbers[0] if numbers else None,
        "max": numbers[-1] if numbers else None,
        "reporting": len(values),
    }


# --------------------------------------------------------- TB screening share
#
# What share of outpatient attendances were screened for TB, counted from the
# start of the year.
#
# Both figures come from HMIS 033B, the WEEKLY surveillance return, so the
# cumulative total is the sum of ISO weeks 1 to the current week. Weeks nobody
# filed contribute nothing rather than a zero, and the count of weeks that did
# report is returned so a thin denominator is visible instead of implied.
#
# The two elements are resolved from the cached 033B listing by name, never
# hard-coded. This application has already shipped mappings aimed at elements
# the Ministry had retired, and the dev metadata cache carries no 033B names at
# all, so a code written in here would be a guess wearing the clothes of a
# fact. The candidates are returned with the figures so the picker can offer
# them and a wrong match is visible and correctable rather than silent.
#
# One shape note: screened-for-TB is a SUBSET of attendance, not a sibling of
# it. A pie of "attendance" against "screened" would draw the screened patients
# twice and its slices would sum to something that is not a population. So the
# split returned here partitions attendance into screened and not screened,
# which is a genuine part-to-whole.

# 033B names vary between instances and the Ministry rewords them between form
# revisions, so these are a first guess at which element is which, never the
# authority. When a guess misses, the endpoint returns the whole 033B list and
# asks the reader to pick rather than refusing to draw anything: a regex that
# does not recognise a name is a reason to offer a choice, not a dead end.
_ATTENDANCE_RE = re.compile(r"attendance|attendances|out[\s-]?patient|\bopd\b", re.I)
_TB_RE = re.compile(r"\btb\b|tubercul", re.I)
_SCREEN_RE = re.compile(r"screen", re.I)

# Recognising the family is not the same as picking the line. 033B carries
# several TB lines and several attendance lines, and putting the matches in
# alphabetical order chooses between them by accident: "Clients diagnosed" wins
# over "Clients Screened" on the C, and a dashboard then quietly draws the
# wrong denominator. So the matches are ranked.
#
# The wanted screening line is the one counted at the door - "TB01. Clients
# Screened for TB at all entry points" - not the narrower counts that follow
# from it, each of which is a subset of it and none of which is the share of
# attendance this card is about. The wanted attendance line is the total, not
# one of its breakdowns.
#
# Ranked, not required: an instance that words its form differently still
# resolves to something reasonable, and the picker still overrides either.
_SCREEN_PREFERRED = re.compile(r"all\s+entry\s+points|\bTB0?1\b", re.I)
_SCREEN_NARROWER = re.compile(
    r"presumptive|presumed|diagnos|confirm|positive|referred|treatment|"
    r"eligible|notified|contact|\bMDR\b|child|under\s*\d", re.I)
_ATTENDANCE_PREFERRED = re.compile(r"\btotal\b", re.I)
_ATTENDANCE_NARROWER = re.compile(
    r"re-?attend|new\s+attend|referral|\bmale\b|\bfemale\b|under\s*\d", re.I)


def _rank(entry: dict, preferred, narrower) -> tuple:
    """Sort key putting the best guess first, then settling ties by name.

    Name length breaks the remaining ties on purpose: between two lines that
    look equally right, the shorter name is the more general one, and the more
    general one is the one this card wants.
    """
    name = entry["label"]
    return (0 if preferred.search(name) else 1,
            1 if narrower.search(name) else 0,
            len(name), name.lower())


def _surveillance_elements() -> dict:
    """033B elements, keyed by id, with their display names."""
    return mapping().get("dataElements", {}).get("HMIS033B") or {}


def tb_screening_candidates() -> dict:
    """The 033B elements that could be the attendance and TB-screening series,
    plus the full list so a missed guess can still be resolved by hand."""
    attendance, screened, every = [], [], []
    for deid, info in _surveillance_elements().items():
        name = (info or {}).get("name") or ""
        entry = {"id": deid, "label": _CODE_PREFIX.sub("", name).strip() or name}
        every.append(entry)
        if _SCREEN_RE.search(name) and _TB_RE.search(name):
            screened.append(entry)
        elif _ATTENDANCE_RE.search(name):
            attendance.append(entry)
    attendance.sort(key=lambda e: _rank(e, _ATTENDANCE_PREFERRED, _ATTENDANCE_NARROWER))
    screened.sort(key=lambda e: _rank(e, _SCREEN_PREFERRED, _SCREEN_NARROWER))
    every.sort(key=lambda e: e["label"].lower())
    return {"attendance": attendance, "screened": screened,
            "all": every, "cached": len(every)}


def _pick(chosen: str, options: list, what: str):
    """The element to use, or None if nothing matched and the caller should ask.

    Raising here was wrong. A name this file failed to recognise is not a
    missing metadata cache, and telling an operator to refresh metadata they
    already have sends them to fix something that is not broken.
    """
    if chosen:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{10}", chosen):
            raise RuntimeError(
                f"Unrecognised {what} element '{chosen}'. Check the parameter; it must "
                "be one of the ids returned by /api/py/tb-screening.")
        return next((o for o in options if o["id"] == chosen),
                    {"id": chosen, "label": "Selected element"})
    return options[0] if options else None


# The outer ring of the screening figure: 105:01 attendance by age band,
# cumulative from January.
#
# 105:01 is MONTHLY, so its year to date is months 1 to the current month, while
# the inner ring's 033B total is weeks 1 to the current week. The two totals
# come from different returns and will not agree; each ring is therefore its own
# whole, and the card says so rather than implying the outer ring subdivides the
# inner one.
#
# Age comes from the category option combo. Analytics returns an element already
# summed across its disaggregation unless `co` is asked for; with it, each row
# carries a combo, and metadata.py's OPD_AGE_SEX table maps a combo to a name
# like "29Dys-4Yrs, Male", whose part before the comma is the band. Sexes are
# folded together because the ring is an age profile, not a sex one.

AGE_BAND_ORDER = ["0-28Dys", "29Dys-4Yrs", "5-9Yrs", "10-19Yrs", "20+Yrs"]
AGE_BAND_LABEL = {
    "0-28Dys": "0 to 28 days",
    "29Dys-4Yrs": "29 days to 4 years",
    "5-9Yrs": "5 to 9 years",
    "10-19Yrs": "10 to 19 years",
    "20+Yrs": "20 years and over",
}


def _age_band_of_combo() -> dict:
    """Category option combo uid -> age band, from the embedded OPD table."""
    combos = (mapping().get("categoryCombos", {}).get("OPD_AGE_SEX") or {}).get("cocs") or {}
    out = {}
    for name, uid in combos.items():
        band = str(name).split(",")[0].strip()
        if band:
            out[uid] = band
    return out


def attendance_by_age(scope: str = "facility", year: int = None, session=None) -> dict:
    """105:01 attendance by age band, months 1 to the current month."""
    index = mapping().get("HMIS105_01_codeIndex") or {}
    ids = [index[c] for c in ("OA01", "OA02") if index.get(c)]
    bands = _age_band_of_combo()
    if not ids or not bands:
        return {"available": False, "bands": [], "total": 0, "monthsCovered": 0,
                "throughMonth": 0, "unclassified": 0}

    today = date.today()
    year = int(year or today.year)
    through = today.month if year == today.year else 12
    periods_list = [f"{year}{m:02d}" for m in range(1, through + 1)]

    h = hierarchy(session=session)
    ou = h[scope]
    res = query(ids, ou["id"], ";".join(periods_list), session=session, co=True)

    totals = {b: 0.0 for b in AGE_BAND_ORDER}
    unclassified = 0.0
    months = set()
    for row in res["rows"]:
        v = _num(row.get("value"))
        if v is None:
            continue
        band = bands.get(row.get("co"))
        if band in totals:
            totals[band] += v
        else:
            # A combo the embedded table does not know is counted and named
            # rather than dropped, so a form revision shows up as a number that
            # does not fit instead of a quietly smaller total.
            unclassified += v
        if row.get("pe"):
            months.add(row["pe"])

    total = sum(totals.values()) + unclassified
    return {
        "available": True,
        "year": year,
        "throughMonth": through,
        "monthsCovered": len(months),
        "periodLabel": f"January to {MONTH_NAMES[through - 1]} {year}",
        "total": int(total),
        "unclassified": int(unclassified),
        "bands": [{"band": b, "label": AGE_BAND_LABEL[b], "value": int(totals[b])}
                  for b in AGE_BAND_ORDER],
    }


def tb_screening(scope: str = "facility", year: int = None, attendance: str = "",
                 screened: str = "", session=None) -> dict:
    scope = (scope or "facility").lower()
    if scope not in SCOPES:
        raise RuntimeError(
            f"Unknown scope '{scope}'. Check the scope parameter; "
            f"the dashboard scopes are: {', '.join(SCOPES)}.")

    options = tb_screening_candidates()
    # Nothing cached at all is the one case that really is a metadata problem.
    if not options["cached"]:
        raise RuntimeError(
            "The HMIS 033B element list is empty, so no series can be resolved. The "
            "cached DHIS2 metadata predates this report. Set DHIS2_USERNAME and "
            "DHIS2_PASSWORD (or DHIS2_PAT) and run Refresh metadata in the admin page.")

    att_el = _pick(attendance, options["attendance"] or options["all"], "attendance")
    scr_el = _pick(screened, options["screened"] or options["all"], "TB screening")

    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    year = int(year or iso_year)
    # Weeks 1 to the current week of the year being read; a past year runs to
    # its own last week rather than stopping where this year happens to be.
    through = iso_week if year == iso_year else iso_weeks_in_year(year)

    base = {
        "scope": scope,
        "year": year,
        "throughWeek": through,
        "periodLabel": f"Weeks 1 to {through}, {year}",
        "elements": {"attendance": att_el, "screened": scr_el},
        "candidates": options,
        # True when this file could not tell which element is which. The figures
        # are withheld rather than guessed, and the caller offers the 033B list.
        "needsChoice": not (options["attendance"] and options["screened"])
                       and not (attendance and screened),
        "matched": {"attendance": bool(options["attendance"]),
                    "screened": bool(options["screened"])},
    }

    h = hierarchy(session=session)
    ou = h[scope]
    base["orgUnit"] = {"id": ou["id"], "name": ou["name"]}

    # The outer ring is independent of which 033B element was chosen, so it is
    # fetched either way: an age profile is still worth drawing while the inner
    # ring waits for someone to pick a series.
    try:
        base["ageProfile"] = attendance_by_age(scope=scope, year=year, session=session)
    except Exception:
        # The outer ring is an addition, not the point of the card. If 105:01
        # cannot be read, the screening split still draws.
        base["ageProfile"] = {"available": False, "bands": [], "total": 0,
                              "monthsCovered": 0, "throughMonth": 0, "unclassified": 0}

    if base["needsChoice"]:
        # A figure drawn from an element nobody confirmed would look exactly as
        # authoritative as a correct one, which is the worst outcome available.
        return {**base, "attendance": None, "screened": None, "notScreened": None,
                "rate": None, "reported": False, "inconsistent": False,
                "weeksReported": 0, "weeksElapsed": through}

    weeks = [f"{year}W{w}" for w in range(1, through + 1)]
    res = query([att_el["id"], scr_el["id"]], ou["id"], ";".join(weeks), session=session)

    totals = {att_el["id"]: 0.0, scr_el["id"]: 0.0}
    reported_weeks = set()
    for row in res["rows"]:
        v = _num(row.get("value"))
        if v is None or row.get("dx") not in totals:
            continue
        totals[row["dx"]] += v
        m = re.fullmatch(r"(\d{4})W(\d{1,2})", str(row.get("pe") or "").upper())
        if m:
            reported_weeks.add(int(m.group(2)))

    att = totals[att_el["id"]]
    scr = totals[scr_el["id"]]
    reported = bool(reported_weeks)

    # More screened than attended cannot be true. It happens when one element
    # was filed and the other was not, and it must not be drawn as a slice
    # larger than the pie.
    inconsistent = reported and scr > att

    return {
        **base,
        "weeksReported": len(reported_weeks),
        "weeksElapsed": through,
        "attendance": int(att),
        "screened": int(scr),
        "notScreened": int(max(0.0, att - scr)),
        "rate": round(100 * scr / att, 1) if att else None,
        "reported": reported,
        "inconsistent": inconsistent,
    }


# ------------------------------------------------------- the malaria channel
#
# A "malaria channel" is the endemic-channel method Uganda uses to decide
# whether this week's malaria burden is an epidemic or simply the season. For
# each ISO week it takes that same week's counts from several previous years
# and reads percentiles off them; the current year is then plotted against
# those bands.
#
# The percentiles are not a free choice. UNIPH's policy brief on detecting
# malaria epidemics (uniph.go.ug) records that Uganda's guidelines use the 3rd
# quartile at health-facility level, and recommends two thresholds - an ALERT
# at the 75th percentile and an EPIDEMIC at the 85th - in preference to the
# mean-plus-two-standard-deviations method, which assumes a normal distribution
# that weekly case counts do not have. It also states the method needs five to
# ten years of history, which is why a shorter baseline is reported rather than
# quietly averaged over whatever happened to be there.

ALERT_PERCENTILE = 75
EPIDEMIC_PERCENTILE = 85
MIN_BASELINE_YEARS = 5

# The floor of the channel. A channel has two walls, and until now only the
# upper one was drawn, so a week far BELOW what the same week has always been
# looked identical to a quiet ordinary week.
#
# There is no Ugandan guidance for the lower bound, because the published work
# is about detecting epidemics rather than detecting their absence. Two
# conventions exist. The endemic-channel tradition (Bortman's canal endemico,
# used across PAHO) divides the year into four zones on the quartiles, making
# the first quartile the boundary of the "success" zone. The older WHO field
# guide draws a channel between the lowest and highest of the previous five
# years.
#
# The 25th percentile is the one that belongs here, because it is the mirror of
# the wall already drawn: Uganda's evaluation of outbreak-detection methods
# (Malaria Journal, 2024) settled on the 75th percentile of the same week over
# five previous years, and the opposite of the 75th is the 25th, not the lowest
# observation. A lowest-of-five floor is also fragile in exactly the way this
# hospital's data is fragile - one week of a stock-out, or one week the register
# was not filed, sets the floor at or near zero for the next five years, and the
# line then never fires again. The minimum and maximum are still reported per
# week, so the fuller range is a hover away.
LOW_PERCENTILE = 25


def _percentile(values: list, p: float):
    """Linear-interpolation percentile, the same convention as numpy's default.

    Written out rather than imported: this module runs in a Vercel function
    where numpy is not a dependency, and the arithmetic is four lines.
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * (p / 100.0)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return float(ordered[low]) * (1 - frac) + float(ordered[high]) * frac


def _median_int(values: list) -> int:
    """The middle value, rounded down. Written out for the same reason as
    _percentile: no numpy in a Vercel function, and it is two lines."""
    if not values:
        return 0
    ordered = sorted(values)
    return int(ordered[len(ordered) // 2])


def iso_weeks_in_year(year: int) -> int:
    """52 or 53. 28 December is always in the last ISO week of its year."""
    return date(year, 12, 28).isocalendar()[1]


def malaria_elements() -> list:
    """The 033B elements that could carry malaria case counts.

    Resolved from the metadata cache by name, never hard-coded. This project
    has already shipped mappings aimed at elements the Ministry had retired,
    and a channel drawn from the wrong element would be worse than no channel:
    it would look authoritative and declare epidemics off the wrong series.
    """
    out = []
    for deid, info in (mapping().get("dataElements", {}).get("HMIS033B") or {}).items():
        name = (info or {}).get("name") or ""
        if not re.search(r"malaria", name, re.I):
            continue
        if not _CASE_NAME.search(name):
            continue
        out.append({"id": deid, "label": _CODE_PREFIX.sub("", name).strip() or name})
    out.sort(key=lambda e: e["label"].lower())
    return out


def region_facilities(session=None) -> list:
    """Every health facility in the region, for the channel's facility picker.

    Read from the hierarchy rather than listed anywhere, so a facility opened or
    renamed in Busoga appears without a code change. Cached with everything else
    here: it is six hundred names that change perhaps twice a year."""
    def produce():
        h = hierarchy(session=session)
        s = _session(session)
        r = s.get(f"{_base()}/api/organisationUnits.json", params=[
            ("filter", f"path:like:{h['region']['id']}"),
            ("filter", f"level:eq:{h['facilityLevel']}"),
            ("fields", "id,name"),
            ("order", "name:asc"),
            ("paging", "false"),
        ], timeout=60)
        r.raise_for_status()
        return [{"id": o["id"], "name": o.get("name") or o["id"]}
                for o in (r.json().get("organisationUnits") or []) if o.get("id")]

    return _cached("region_facilities", produce)


def _resolve_org_unit(ou: str, scope: str, session=None) -> dict:
    """The org unit a channel is drawn for: one of the three scopes, or a named
    facility within the region.

    A free-text org unit id is not accepted on trust. Anything outside Busoga
    would draw a channel this hospital has no business publishing, and a typo
    would otherwise reach DHIS2 as a request for a unit that does not exist and
    come back as an analytics error nobody can act on."""
    h = hierarchy(session=session)
    if not ou:
        return h[scope]
    ou = str(ou).strip()
    for known in (h["facility"], h["region"], h["national"]):
        if ou == known["id"]:
            return known
    match = next((f for f in region_facilities(session=session) if f["id"] == ou), None)
    if not match:
        raise RuntimeError(
            f"'{ou}' is not a facility in {h['region']['name']}. Use this hospital, the "
            "region, the country, or any facility in the regional list at "
            "/api/py/malaria/facilities.")
    return {**match, "scope": "facility", "level": h["facilityLevel"]}


def malaria_channel(element: str = "", scope: str = "facility", year: int = None,
                    baseline: int = MIN_BASELINE_YEARS, ou: str = "",
                    session=None) -> dict:
    """Weekly case counts against percentile bands built from previous years."""
    scope = (scope or "facility").lower()
    if scope not in SCOPES:
        raise RuntimeError(
            f"Unknown scope '{scope}'. Check the scope parameter; "
            f"the dashboard scopes are: {', '.join(SCOPES)}.")

    candidates = malaria_elements()
    if element:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{10}", element):
            raise RuntimeError(
                f"Unrecognised data element '{element}'. Check the element parameter; "
                "it must be one of the ids returned by /api/py/malaria/elements.")
        chosen = next((c for c in candidates if c["id"] == element),
                      {"id": element, "label": "Selected element"})
    elif candidates:
        chosen = candidates[0]
    else:
        raise RuntimeError(
            "No 033B malaria case element is available. The cached DHIS2 metadata "
            "predates the surveillance report or does not carry element names. Set "
            "DHIS2_USERNAME and DHIS2_PASSWORD (or DHIS2_PAT) and run Refresh metadata "
            "in the admin page.")

    today = date.today()
    # The channel is read against the year in progress, and the baseline is the
    # years before it - never the current one, which would let an epidemic
    # raise its own threshold.
    year = int(year or today.isocalendar()[0])
    baseline = max(1, min(int(baseline or MIN_BASELINE_YEARS), 10))
    baseline_years = list(range(year - baseline, year))

    # The scope names one of the three standing org units; `ou` overrides it
    # with a named facility, which is how a peer hospital is charted. The
    # parameter is resolved into `target` rather than reassigned, so the two
    # never shadow one another.
    h = hierarchy(session=session)
    target = _resolve_org_unit(ou, scope, session=session)
    charted = next((s for s in SCOPES if h[s]["id"] == target["id"]), "other")

    def weekly(y):
        weeks = [f"{y}W{w}" for w in range(1, iso_weeks_in_year(y) + 1)]
        res = query([chosen["id"]], target["id"], ";".join(weeks), session=session)
        out = {}
        for row in res["rows"]:
            m = re.fullmatch(r"(\d{4})W(\d{1,2})", str(row.get("pe") or "").upper())
            v = _num(row.get("value"))
            if m and v is not None:
                out[int(m.group(2))] = v
        return out

    history = {y: weekly(y) for y in baseline_years}
    current = weekly(year)

    max_week = iso_weeks_in_year(year)
    weeks = []
    for w in range(1, max_week + 1):
        past = [history[y][w] for y in baseline_years if w in history[y]]
        weeks.append({
            "week": w,
            "n": len(past),
            "low": _percentile(past, LOW_PERCENTILE),
            "median": _percentile(past, 50),
            "alert": _percentile(past, ALERT_PERCENTILE),
            "epidemic": _percentile(past, EPIDEMIC_PERCENTILE),
            # The observed extremes, for the tooltip. Not drawn: a line through
            # the highest of five years is a line through five different years,
            # and it reads as a threshold when it is only a record.
            "min": min(past) if past else None,
            "max": max(past) if past else None,
            "current": current.get(w),
        })

    # Where the latest reported week sits, which is the question the chart is
    # drawn to answer.
    latest = next((w for w in reversed(weeks) if w["current"] is not None), None)
    if latest is None or latest["epidemic"] is None:
        status = "unknown"
    elif latest["current"] > latest["epidemic"]:
        status = "epidemic"
    elif latest["alert"] is not None and latest["current"] > latest["alert"]:
        status = "alert"
    elif latest["low"] is not None and latest["current"] < latest["low"]:
        # Worth saying, and not an epidemic signal. At this hospital a week well
        # below every previous year has more often meant the return was filed
        # short than that malaria receded.
        status = "low"
    else:
        status = "normal"

    covered = [len([1 for y in baseline_years if w["week"] in history[y]]) for w in weeks]
    return {
        "element": chosen,
        "elements": candidates,
        "orgUnit": {"id": target["id"], "name": target["name"]},
        # What was actually charted: the scope asked for, or "other" when a
        # named facility overrode it, so the control can show what is selected
        # without re-deriving it from the org unit id.
        "scope": charted,
        "year": year,
        "baselineYears": baseline_years,
        "lowPercentile": LOW_PERCENTILE,
        "alertPercentile": ALERT_PERCENTILE,
        "epidemicPercentile": EPIDEMIC_PERCENTILE,
        "weeks": weeks,
        "latestWeek": latest["week"] if latest else None,
        "status": status,
        # Said plainly rather than hidden: a channel built on two years is not
        # the method the guidelines describe, and the reader must know that
        # before acting on a threshold drawn from it.
        #
        # The TYPICAL week, not the best one. This reported the maximum, and at
        # Jinja the maximum is 5 while the median week is built on 3 and some
        # weeks on 1: one well-covered week in the year was enough to silence
        # the warning for all fifty-three. A reader was told "5 previous years"
        # over a chart whose limits mostly came from three.
        "baselineYearsUsed": _median_int(covered),
        "baselineYearsBest": max(covered) if covered else 0,
        "baselineBelowGuidance": _median_int(covered) < MIN_BASELINE_YEARS,
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
