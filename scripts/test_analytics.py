"""Checks for the regional and national figures, offline.

The two wider dashboard tabs read DHIS2 analytics, and analytics is the one
part of this application whose answers cannot be reproduced locally: they come
from four hundred facilities and a nightly aggregation run. So the DHIS2
session is stubbed with a fixture that reproduces the *shape* of a real
response, including the three things that have historically been got wrong.

    python scripts/test_analytics.py

Needs neither a database, credentials, nor a network.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import analytics  # noqa: E402
from _lib import metadata  # noqa: E402
import re as _re  # noqa: E402
from datetime import date as _date  # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


# ---------------------------------------------------------------- the stub

FACILITY = "SZS6IdnTKZR"
REGION = "BUSOGArgn01"
NATIONAL = "UGANDAroot1"

# Two peers plus the hospital, deliberately including a tie so the dense
# ranking is exercised rather than assumed.
PEERS = {
    "fac_kamuli1": ("Kamuli General Hospital", 100.0),
    FACILITY: ("Jinja Regional Referral Hospital", 92.0),
    "fac_iganga1": ("Iganga District Hospital", 92.0),
    "fac_mayuge1": ("Mayuge HC IV", 40.0),
}


class Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected raise_for_status at {self.status_code}")


class StubSession:
    """Answers the two URLs analytics.py calls, and records every request so
    the tests can assert on what was asked, not only on what came back."""

    def __init__(self, status=200):
        self.calls = []
        self.status = status

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params or {}))
        if url.endswith("/api/organisationUnits.json"):
            if self.status >= 400:
                return Response({}, self.status)
            return Response({"organisationUnits": [
                # A plain Polygon.
                {"id": "dist_jinja", "name": "Jinja City", "level": 3, "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[33.2, 0.4], [33.3, 0.4], [33.3, 0.5], [33.2, 0.5], [33.2, 0.4]]]}},
                # A MultiPolygon, which islands in Lake Victoria genuinely need.
                {"id": "dist_mayuge", "name": "Mayuge District", "level": 3, "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [[[[33.4, 0.2], [33.6, 0.2], [33.6, 0.35], [33.4, 0.35], [33.4, 0.2]]],
                                    [[[33.55, 0.05], [33.62, 0.05], [33.62, 0.12], [33.55, 0.12], [33.55, 0.05]]]]}},
                # Coordinates carrying more precision than a district needs.
                {"id": "dist_kamuli", "name": "Kamuli District", "level": 3, "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[33.10987654, 0.90123456], [33.2, 0.9], [33.2, 1.1],
                                     [33.1, 1.1], [33.10987654, 0.90123456]]]}},
                # No geometry at all - must be named, not silently dropped.
                {"id": "dist_nogeo", "name": "Bugweri District", "level": 3},
                # A point, which cannot be shaded and must be skipped.
                {"id": "dist_point", "name": "A Facility", "level": 6,
                 "geometry": {"type": "Point", "coordinates": [33.2, 0.44]}},
                # A position carrying altitude as a third ordinate, which is
                # legal GeoJSON and used to make the whole district vanish.
                {"id": "dist_alt", "name": "Buyende District", "level": 3, "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[33.0, 1.1, 1140.0], [33.1, 1.1, 1140.0],
                                     [33.1, 1.2, 1140.0], [33.0, 1.2, 1140.0],
                                     [33.0, 1.1, 1140.0]]]}},
                # Pre-2.36 DHIS2: a `coordinates` JSON string, no `geometry`.
                {"id": "dist_legacy", "name": "Kaliro District", "level": 3,
                 "featureType": "MULTI_POLYGON",
                 "coordinates": "[[[[33.7,1.0],[33.8,1.0],[33.8,1.1],[33.7,1.1],[33.7,1.0]]]]"},
            ]})
        if "/organisationUnits/" in url:
            return Response({
                "id": FACILITY, "name": "Jinja Regional Referral Hospital", "level": 6,
                "path": f"/{NATIONAL}/{REGION}/dist01/subc01/parent1/{FACILITY}",
                "ancestors": [
                    {"id": NATIONAL, "name": "Uganda", "level": 1},
                    {"id": REGION, "name": "Busoga Region", "level": 2},
                    {"id": "dist01", "name": "Jinja District", "level": 3},
                    {"id": "subc01", "name": "Jinja City", "level": 4},
                    {"id": "parent1", "name": "Central Division", "level": 5},
                ],
            })
        if self.status >= 400:
            return Response({}, self.status)
        return Response(self._analytics(params))

    def _analytics(self, params):
        dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in params.get("dimension", [])}
        dx = dims.get("dx", "").split(";")
        pe = dims.get("pe", "")
        ou = dims.get("ou", "")

        rows, items = [], {}

        # A per-facility request: one row per peer.
        if ou.startswith("LEVEL-"):
            for uid, (name, rate) in PEERS.items():
                rows.append([dx[0], pe, uid, str(rate)])
                items[uid] = {"name": name}
            return {"headers": [{"name": "dx"}, {"name": "pe"}, {"name": "ou"},
                                {"name": "value"}],
                    "metaData": {"items": items}, "rows": rows}

        # A relative period: twelve monthly buckets.
        if pe.startswith("LAST_"):
            for i, month in enumerate(["202509", "202510", "202511", "202512"]):
                for d in dx:
                    rows.append([d, month, ou, str(80 + i)])
            return {"headers": [{"name": "dx"}, {"name": "pe"}, {"name": "ou"},
                                {"name": "value"}],
                    "metaData": {"items": {}}, "rows": rows}

        for d in dx:
            # HMIS106A_03 stands in for a data set analytics has not run yet:
            # it returns no row at all, which must not read as zero.
            if d.startswith("DFMoIONIalm"):
                continue
            if d.endswith(".REPORTING_RATE"):
                value = "92.0"
            elif d.endswith(".REPORTING_RATE_ON_TIME"):
                value = "75.0"
            elif d.endswith(".ACTUAL_REPORTS_ON_TIME"):
                value = "30"
            elif d.endswith(".ACTUAL_REPORTS"):
                value = "40"
            elif d.endswith(".EXPECTED_REPORTS"):
                value = "50"
            else:
                value = "1234"
            rows.append([d, pe, ou, value])
        return {"headers": [{"name": "dx"}, {"name": "pe"}, {"name": "ou"},
                            {"name": "value"}],
                "metaData": {"items": {}}, "rows": rows}


def fresh(status=200):
    analytics.reset_cache()
    return StubSession(status=status)


# The mapping is read straight from metadata.py's embedded constants; only the
# data element listings need the network, and nothing here touches them.
metadata._MAPPING = dict(metadata.CONSTANTS)
metadata._MAPPING["dataElements"] = {}


# --------------------------------------------------------------- hierarchy

print("\nThe three scopes are resolved from the facility's own ancestors")
s = fresh()
h = analytics.hierarchy(session=s)
check("the facility is the configured org unit", h["facility"]["id"], FACILITY)
check("the region is the level-2 ancestor", h["region"]["id"], REGION)
check("...and carries its real name", h["region"]["name"], "Busoga Region")
check("the nation is the level-1 ancestor", h["national"]["id"], NATIONAL)
check("the facility's own level is kept for peer queries", h["facilityLevel"], 6)
check("one lookup answers all three", len(s.calls), 1)

print("\nThe hierarchy is memoised, so switching tabs does not re-query it")
before = len(s.calls)
analytics.hierarchy(session=s)
check("a second call makes no request", len(s.calls), before)

print("\nA hierarchy that does not reach the expected level says what to set")
saved = analytics.REGION_LEVEL
analytics.REGION_LEVEL = 9
s = fresh()
try:
    analytics.hierarchy(session=s)
    check("a missing region raises", True, False)
except RuntimeError as exc:
    check("a missing region raises RuntimeError", True, True)
    check("...and names the variable to set", "DHIS2_REGION_OU" in str(exc), True)
analytics.REGION_LEVEL = saved

print("\nThe tab list is facility-first and labelled for the navbar")
s = fresh()
tabs = analytics.scopes(session=s)
check("three scopes", [t["scope"] for t in tabs], ["facility", "region", "national"])
check("the facility tab is short-labelled", tabs[0]["short"], "Jinja RRH")
check("the national tab is short-labelled", tabs[2]["short"], "MoH - National")
check("the facility's figures are local, not analytics", tabs[0]["source"], "local")

# ------------------------------------------------------------- completeness

print("\nEach data set is asked with a period of its own cadence")
# A weekly data set asked over a month silently aggregates five weeks and
# reports a rate above 100. Grouping by periodType is what prevents it.
s = fresh()
sets = analytics.completeness(REGION, session=s)
asked = {}
for url, params in s.calls:
    if "analytics" not in url:
        continue
    dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in params["dimension"]}
    asked[dims["pe"]] = dims["dx"]
check("one request per cadence, not one per data set", len(asked), 3)
weekly = [pe for pe in asked if "W" in pe]
monthly = [pe for pe in asked if len(pe) == 6 and pe.isdigit()]
quarterly = [pe for pe in asked if "Q" in pe]
check("a weekly period was used", len(weekly), 1)
check("a monthly period was used", len(monthly), 1)
check("a quarterly period was used", len(quarterly), 1)

by_type = {e["type"]: e for e in sets}
check("all eight registered data sets are reported on", len(sets), 8)
check("the weekly data set was asked with the weekly period",
      "W" in by_type["SURV"]["period"], True)
check("the monthly data set was asked with the monthly period",
      by_type["OPD"]["period"].isdigit(), True)

print("\nA rate is parsed, not passed through as a string")
check("reporting rate is a number", by_type["OPD"]["reportingRate"], 92.0)
check("actual reports is an integer", by_type["OPD"]["actual"], 40)
check("expected reports is an integer", by_type["OPD"]["expected"], 50)
check("on-time count is an integer", by_type["OPD"]["onTime"], 30)

print("\nA period analytics has not run for is missing, not zero")
# Showing an un-run period as 0% would say four hundred facilities failed to
# report when in fact nobody has asked them yet.
check("the un-run data set is marked stale", by_type["TBL"]["stale"], True)
check("...and its rate is None rather than 0", by_type["TBL"]["reportingRate"], None)
check("a data set with figures is not stale", by_type["OPD"]["stale"], False)

# ------------------------------------------------------------------ ranking

print("\nThe hospital is ranked among the facilities of its region")
s = fresh()
rank = analytics.ranking(session=s)
peer_call = [p for u, p in s.calls if "analytics" in u][0]
dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in peer_call["dimension"]}
check("peers are asked for at the facility level, under the region",
      dims["ou"], f"LEVEL-6;{REGION}")
check("every facility that reported is counted", rank["of"], 4)
check("a tie shares the better rank", rank["rank"], 2)
check("the leader is rank 1", rank["top"][0]["rank"], 1)
check("...and is named from metaData rather than shown as a UID",
      rank["top"][0]["name"], "Kamuli General Hospital")
check("the hospital's own row is returned", rank["facility"]["id"], FACILITY)
check("ranking is on one named data set, not an average", rank["dataSet"], "105:01")

# ------------------------------------------------------------------ overview

print("\nThe overview is one payload per scope")
s = fresh()
ov = analytics.overview("region", session=s)
check("it names the org unit it describes", ov["orgUnit"]["id"], REGION)
check("four tiles, matching the facility tab", len(ov["tiles"]), 4)
check("every data set is listed", len(ov["dataSets"]), 8)
check("a trend is included", len(ov["trend"]) > 0, True)
check("headline indicators are included", len(ov["indicators"]) > 0, True)
check("the region tab carries the peer ranking", "ranking" in ov, True)

# Seven of the eight data sets answered, each 40 of 50 => 280 of 350 => 80.0%.
# The eighth (quarterly TB/Leprosy) has not been aggregated yet and is left
# out of both the numerator and the denominator, which is the whole point:
# counting it as 0 of 50 would drag the region's rate down to 70% on the
# strength of a run that has not happened.
rate = [t for t in ov["tiles"] if t["label"] == "Reporting rate"][0]
check("the rate tile is computed from the sets that answered", rate["value"], 80.0)
check("...and is a percentage", rate["unit"], "%")
received = [t for t in ov["tiles"] if t["label"] == "Reports received"][0]
check("the received tile sums actual reports", received["value"], 280)
check("...over only the sets that answered", received["foot"], "of 350 expected")

print("\nStale data sets are excluded from the totals, not counted as zero")
tracked = [t for t in ov["tiles"] if t["label"] == "Data sets tracked"][0]
check("all eight are tracked", tracked["value"], 8)
check("...but the footnote says how many answered",
      "7 with figures" in tracked["foot"], True)

print("\nThe facility scope carries no peer ranking")
s = fresh()
own = analytics.overview("facility", session=s)
check("ranking is absent on the hospital's own tab", "ranking" in own, False)
check("it still names the hospital", own["orgUnit"]["id"], FACILITY)

print("\nAn unknown scope is refused by name")
try:
    analytics.overview("district", session=fresh())
    check("an unknown scope raises", True, False)
except RuntimeError as exc:
    check("an unknown scope raises RuntimeError", True, True)
    check("...and lists the ones that exist", "facility, region, national" in str(exc), True)

print("\nA refused read explains the permission, not the status code")
# The commonest real failure: an account that can submit for the hospital but
# holds no data-read sharing above it. A bare 403 would send the reader to the
# wrong place entirely.
s = fresh(status=403)
try:
    analytics.completeness(REGION, session=s)
    check("a 403 raises", True, False)
except RuntimeError as exc:
    msg = str(exc)
    check("a 403 raises RuntimeError", True, True)
    check("...and says it is about read sharing", "data-read sharing" in msg, True)
    check("...and names the variables to change", "DHIS2_USERNAME" in msg, True)

# --------------------------------------------------------------------- map

print("\nDistrict outlines come from DHIS2, not from a checked-in shapefile")
s = fresh()
geo = analytics.districts(session=s)
ou_call = [p for u, p in s.calls if u.endswith("/api/organisationUnits.json")][0]
check("districts are the region's own children",
      ou_call["filter"], f"parent.id:eq:{REGION}")
check("geometry is asked for", "geometry" in ou_call["fields"], True)
check("paging is off, so a region is never truncated", ou_call["paging"], "false")

names = [d["name"] for d in geo["districts"]]
check("only shadeable shapes are kept",
      names, ["Buyende District", "Jinja City", "Kaliro District",
              "Kamuli District", "Mayuge District"])
check("a Point is skipped rather than drawn", "A Facility" in names, False)
# Both of these used to drop a whole district without a word.
check("a position with altitude keeps its district", "Buyende District" in names, True)
check("...and the altitude ordinate is discarded",
      [d for d in geo["districts"] if d["name"] == "Buyende District"][0]
      ["geometry"]["coordinates"][0][0], [33.0, 1.1])
check("a pre-2.36 coordinates string is understood", "Kaliro District" in names, True)
check("a district with no boundary is named, not silently dropped",
      geo["withoutGeometry"], ["Bugweri District"])

kinds = {d["name"]: d["geometry"]["type"] for d in geo["districts"]}
check("a Polygon survives as a Polygon", kinds["Jinja City"], "Polygon")
check("a MultiPolygon survives as a MultiPolygon", kinds["Mayuge District"], "MultiPolygon")
check("both islands of the MultiPolygon are kept",
      len([d for d in geo["districts"] if d["name"] == "Mayuge District"][0]["geometry"]["coordinates"]), 2)

kamuli = [d for d in geo["districts"] if d["name"] == "Kamuli District"][0]
check("coordinates are rounded to district precision",
      kamuli["geometry"]["coordinates"][0][0], [33.1099, 0.9012])

check("the bounding box spans every shape", geo["bbox"], [33.0, 0.05, 33.8, 1.2])
check("the hospital's own district is named so the map can mark it",
      geo["facilityDistrict"], "dist01")

print("\nOutlines are cached far longer than the figures")
before = len([u for u, _ in s.calls if u.endswith("/api/organisationUnits.json")])
analytics.districts(session=s)
check("a second call re-uses them",
      len([u for u, _ in s.calls if u.endswith("/api/organisationUnits.json")]), before)

print("\nThe indicator catalogue is derived from the registry")
groups = {g["group"]: g["items"] for g in analytics.map_indicators()}
check("reporting rate is offered per data set", len(groups["Reporting rate"]), 8)
check("so is on-time filing", len(groups["On-time filing"]), 8)
check("service volume comes from keyDataElements", len(groups["Service volume"]), 5)
check("a rate is a percentage", groups["Reporting rate"][0]["unit"], "%")
check("a volume figure is a count", groups["Service volume"][0]["kind"], "count")
check("each item carries the cadence its periods must come from",
      sorted({i["periodType"] for i in groups["Reporting rate"]}),
      ["Monthly", "Quarterly", "Weekly"])
# The cache in this fixture has no 033B listing, exactly as a deployment that
# has not refreshed metadata since 033B was added. Inventing disease names to
# fill the gap is the mistake this project has already made once.
check("no surveillance group is invented when 033B is not cached",
      "Surveillance cases" in groups, False)

print("\n...and grows a surveillance group when 033B metadata arrives")
metadata._MAPPING["dataElements"] = {"HMIS033B": {
    "de033bchol": {"name": "033B-CD01a. Cholera Cases"},
    "de033bmeas": {"name": "033B-CD02. Measles Cases"},
    "de033bdead": {"name": "033B-CD01b. Cholera Deaths"},
    "de033bgene": {"name": "033B-ST04. GeneXpert modules working"},
}}
groups = {g["group"]: g["items"] for g in analytics.map_indicators()}
surv = groups.get("Surveillance cases", [])
check("only case counts are offered", [i["label"] for i in surv],
      ["Cholera Cases", "Measles Cases"])
check("the HMIS code prefix is stripped for reading",
      surv[0]["label"].startswith("033B-"), False)
check("deaths and equipment are not offered as cases",
      any("Deaths" in i["label"] or "GeneXpert" in i["label"] for i in surv), False)
check("surveillance is weekly", surv[0]["periodType"], "Weekly")
metadata._MAPPING["dataElements"] = {}

print("\nPeriods are offered per cadence, newest first")
months = analytics.recent_periods("Monthly", 12)
check("twelve months", len(months), 12)
check("each is YYYYMM", all(len(p["period"]) == 6 and p["period"].isdigit() for p in months), True)
check("newest first", months[0]["period"] > months[1]["period"], True)
check("weeks are ISO weeks", "W" in analytics.recent_periods("Weekly", 4)[0]["period"], True)
check("quarters are quarters", "Q" in analytics.recent_periods("Quarterly", 4)[0]["period"], True)

print("\nAn indicator resolves to the right analytics item")
s = fresh()
vals = analytics.map_values("rate:RtEYsASU7PG", "202607", session=s)
call = [p for u, p in s.calls if "analytics" in u][0]
dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in call["dimension"]}
check("a rate becomes .REPORTING_RATE", dims["dx"], "RtEYsASU7PG.REPORTING_RATE")
check("districts are asked for, not facilities", dims["ou"], f"LEVEL-3;{REGION}")
check("it is a percentage", vals["kind"], "percent")

s = fresh()
analytics.map_values("ontime:RtEYsASU7PG", "202607", session=s)
dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in
        [p for u, p in s.calls if "analytics" in u][0]["dimension"]}
check("on-time becomes .REPORTING_RATE_ON_TIME", dims["dx"], "RtEYsASU7PG.REPORTING_RATE_ON_TIME")

s = fresh()
raw = analytics.map_values("de:sv6SeKroHPV", "202607", session=s)
dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in
        [p for u, p in s.calls if "analytics" in u][0]["dimension"]}
check("a data element is passed through unsuffixed", dims["dx"], "sv6SeKroHPV")
check("...and is a count, not a percentage", raw["kind"], "count")

print("\nA district that returned nothing is absent, not zero")
# The stub answers for every org unit it is given, so this asserts the shape
# rather than the fixture: only districts with a row appear in `values`.
check("values are keyed by organisation unit", isinstance(vals["values"], dict), True)
check("the count of reporting districts is stated", vals["reporting"], len(vals["values"]))
check("min and max are given for the legend",
      vals["min"] is not None and vals["max"] is not None, True)

print("\nA malformed indicator or period is refused before DHIS2 is called")
for bad, why in [("nonsense", "no prefix"), ("rate:short", "not a UID"),
                 ("weird:RtEYsASU7PG", "unknown prefix")]:
    try:
        analytics.map_values(bad, "202607", session=fresh())
        check(f"{why} is refused", True, False)
    except RuntimeError as exc:
        check(f"{why} is refused", "Check the indicator parameter" in str(exc), True)
try:
    analytics.map_values("rate:RtEYsASU7PG", "July", session=fresh())
    check("a malformed period is refused", True, False)
except RuntimeError as exc:
    check("a malformed period is refused", "Check the period parameter" in str(exc), True)

print("\nA refused district listing explains the permission")
s = fresh(status=403)
try:
    analytics.districts(session=s)
    check("a 403 on the listing raises", True, False)
except RuntimeError as exc:
    check("a 403 on the listing raises RuntimeError", True, True)
    check("...and names the variables to change", "DHIS2_USERNAME" in str(exc), True)

# --------------------------------------------------------- malaria channel

print("\nPercentiles match the linear-interpolation convention")
# These thresholds decide whether an epidemic is declared, so the arithmetic is
# pinned to known values rather than trusted.
p = analytics._percentile
check("median of an odd run", p([1, 2, 3, 4, 5], 50), 3.0)
check("median of an even run interpolates", p([1, 2, 3, 4], 50), 2.5)
check("75th of five", p([10, 20, 30, 40, 50], 75), 40.0)
check("85th of five interpolates", round(p([10, 20, 30, 40, 50], 85), 2), 44.0)
check("a single year gives that year", p([7], 75), 7.0)
check("an empty baseline gives nothing, not zero", p([], 75), None)

print("\nISO years of 52 and 53 weeks are both handled")
check("2026 has 53 ISO weeks", analytics.iso_weeks_in_year(2026), 53)
check("2025 has 52", analytics.iso_weeks_in_year(2025), 52)

print("\nThe thresholds are the ones Uganda's guidance names")
check("alert is the 75th percentile", analytics.ALERT_PERCENTILE, 75)
check("epidemic is the 85th percentile", analytics.EPIDEMIC_PERCENTILE, 85)
check("five years is the documented minimum baseline", analytics.MIN_BASELINE_YEARS, 5)


class ChannelSession(StubSession):
    """Weekly malaria counts: a flat baseline, then a current year that climbs
    through the alert band and out the top of the channel."""

    BASE = {2021: 100, 2022: 110, 2023: 90, 2024: 120, 2025: 105}

    def _analytics(self, params):
        dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in params.get("dimension", [])}
        rows = []
        for pe in dims.get("pe", "").split(";"):
            m = __import__("re").fullmatch(r"(\d{4})W(\d{1,2})", pe)
            if not m:
                continue
            year, week = int(m.group(1)), int(m.group(2))
            if year in self.BASE:
                rows.append([dims["dx"], pe, dims["ou"], str(self.BASE[year])])
            elif year == 2026 and week <= 10:
                # 5 normal weeks, then alert, then frank epidemic.
                rows.append([dims["dx"], pe, dims["ou"],
                             str(95 if week <= 5 else 113 if week <= 7 else 400)])
        return {"headers": [{"name": "dx"}, {"name": "pe"}, {"name": "ou"}, {"name": "value"}],
                "metaData": {"items": {}}, "rows": rows}


metadata._MAPPING["dataElements"] = {"HMIS033B": {
    "de033bmala": {"name": "033B-CD05a. Malaria Cases"},
    "de033bmalb": {"name": "033B-CD05b. Malaria Deaths"},
    "de033bchol": {"name": "033B-CD01a. Cholera Cases"},
}}

print("\nThe malaria element is resolved from metadata, never hard-coded")
els = analytics.malaria_elements()
check("only malaria case elements are offered", [e["label"] for e in els], ["Malaria Cases"])
check("malaria deaths are not a case series",
      any("Deaths" in e["label"] for e in els), False)

print("\nThe channel is built from the years before the one being read")
analytics.reset_cache()
s = ChannelSession()
ch = analytics.malaria_channel(scope="facility", year=2026, baseline=5, session=s)
check("the baseline is the five preceding years", ch["baselineYears"], [2021, 2022, 2023, 2024, 2025])
check("the current year is not in its own baseline", 2026 in ch["baselineYears"], False)
check("2026 is a 53-week year", len(ch["weeks"]), 53)
check("the element chosen is the malaria one", ch["element"]["id"], "de033bmala")

w1 = ch["weeks"][0]
check("five baseline years contributed", w1["n"], 5)
# sorted 90,100,105,110,120 -> median 105, p75 110, p85 114
check("the median is the middle year", w1["median"], 105.0)
check("the alert line is the 75th percentile", w1["alert"], 110.0)
check("the epidemic line is the 85th percentile", round(w1["epidemic"], 1), 114.0)

print("\nA week is classified against its own week's bands")
check("a quiet week reads as normal", ch["weeks"][0]["current"], 95.0)
check("week 6 crosses the alert line", ch["weeks"][5]["current"] > ch["weeks"][5]["alert"], True)
check("...but not the epidemic line", ch["weeks"][5]["current"] > ch["weeks"][5]["epidemic"], False)
check("week 8 clears the epidemic line", ch["weeks"][7]["current"] > ch["weeks"][7]["epidemic"], True)
check("the latest reported week is the one classified", ch["latestWeek"], 10)
check("and the facility is in epidemic", ch["status"], "epidemic")

print("\nWeeks with no report are absent, not zero")
check("a future week carries no current value", ch["weeks"][20]["current"], None)
check("...and still carries its bands", ch["weeks"][20]["alert"], 110.0)

print("\nA baseline shorter than the guidance says so")
analytics.reset_cache()
short = analytics.malaria_channel(scope="facility", year=2026, baseline=2,
                                  session=ChannelSession())
check("two years is fewer than the five the method needs",
      short["baselineBelowGuidance"], True)
check("...and the number actually used is reported", short["baselineYearsUsed"], 2)
check("a full baseline is not flagged", ch["baselineBelowGuidance"], False)

print("\nAn unusable request is refused with something to act on")
try:
    analytics.malaria_channel(scope="district", session=ChannelSession())
    check("an unknown scope raises", True, False)
except RuntimeError as exc:
    check("an unknown scope raises", "Check the scope parameter" in str(exc), True)
try:
    analytics.malaria_channel(element="nope", session=ChannelSession())
    check("a malformed element raises", True, False)
except RuntimeError as exc:
    check("a malformed element raises", "Check the element parameter" in str(exc), True)

metadata._MAPPING["dataElements"] = {}
analytics.reset_cache()
try:
    analytics.malaria_channel(session=ChannelSession())
    check("no malaria element raises", True, False)
except RuntimeError as exc:
    check("no malaria element raises RuntimeError", True, True)
    check("...and says to refresh metadata", "Refresh metadata" in str(exc), True)

# ----------------------------------------------------------- TB screening

class ScreeningSession(StubSession):
    """033B weekly attendance and TB screening. Weeks 1 to 20 reported; 21
    onwards have not been filed yet."""

    ATT, SCR = "de033batt01", "de033btb001"
    PER_WEEK = {ATT: 340, SCR: 85}
    REPORTED_THROUGH = 20

    def _analytics(self, params):
        dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in params.get("dimension", [])}
        rows = []
        for pe in dims.get("pe", "").split(";"):
            m = _re.fullmatch(r"(\d{4})W(\d{1,2})", pe)
            if not m or int(m.group(2)) > self.REPORTED_THROUGH:
                continue
            for dx in dims["dx"].split(";"):
                if dx in self.PER_WEEK:
                    rows.append([dx, pe, dims["ou"], str(self.PER_WEEK[dx])])
        return {"headers": [{"name": "dx"}, {"name": "pe"}, {"name": "ou"}, {"name": "value"}],
                "metaData": {"items": {}}, "rows": rows}


metadata._MAPPING["dataElements"] = {"HMIS033B": {
    "de033batt01": {"name": "033B-AP01. Total OPD Attendance"},
    "de033btb001": {"name": "033B-TB01. Number screened for TB"},
    "de033bmal01": {"name": "033B-CD01a. Malaria (Confirmed) - Cases"},
    "de033bdth01": {"name": "033b-AP03. Total Deaths"},
}}

print("\nBoth series come from 033B, matched by name rather than hard-coded")
cands = analytics.tb_screening_candidates()
check("the attendance series is found", [c["id"] for c in cands["attendance"]], ["de033batt01"])
check("the TB screening series is found", [c["id"] for c in cands["screened"]], ["de033btb001"])
check("the code prefix is stripped for reading",
      cands["attendance"][0]["label"], "Total OPD Attendance")
# "Total Deaths" is not attendance and must not be offered as it.
check("an unrelated 033B element is not offered",
      any(c["label"] == "Total Deaths" for c in cands["attendance"]), False)

print("\nSeveral 033B lines match; the one counted at the door is picked first")
# The form carries a TB line for each stage of the cascade and each later one
# is a subset of the screening line, so the order the matches come back in
# decides the denominator the dashboard draws. Alphabetical order decides it by
# accident: "Clients diagnosed" beats "Clients Screened" on the C.
_SAVED_033B = metadata._MAPPING["dataElements"]
metadata._MAPPING["dataElements"] = {"HMIS033B": {
    # Every one of these sorts before the wanted line alphabetically, so this
    # fixture fails outright if the order goes back to being the alphabet's.
    "de033btb002": {"name": "033B-TB02. Clients screened and found presumptive for TB"},
    "de033btb003": {"name": "033B-TB03. Clients screened who were diagnosed with TB"},
    "de033btb001": {"name": "033B-TB01. Clients Screened for TB at all entry points"},
    "de033btb004": {"name": "033B-TB04. Children screened for TB among contacts"},
    "de033btb005": {"name": "033B-TB05. Presumptive TB clients investigated"},
    "de033batt02": {"name": "033B-AP02. OPD Re-attendance"},
    "de033batt01": {"name": "033B-AP01. Total OPD Attendance"},
}}
# The two lines this hospital's form actually uses, checked by name against
# lines built to beat them: "Total OPD attendance under 5 years" also says
# "total" and also says "attendance", and it is not the denominator.
metadata._MAPPING["dataElements"]["HMIS033B"].update({
    "de033bap02x": {"name": "033B-AP02. Total OPD Attendance"},
    "de033bap0u5": {"name": "033B-AP04. Total OPD Attendance under 5 years"},
    "de033bap0op": {"name": "033B-AP05. Total outpatient department contacts"},
})
analytics.reset_cache()
ranked = analytics.tb_screening_candidates()
check("the entry-point screening line is offered first",
      ranked["screened"][0]["label"], "Clients Screened for TB at all entry points")
# Among themselves the narrower counts tie, and the tie breaks on name length:
# between two lines that look equally right the shorter name is the more
# general one. Which of them comes second does not matter; that none of them
# comes first does.
check("...and the narrower counts that follow from it come after",
      [c["id"] for c in ranked["screened"]][1:],
      ["de033btb004", "de033btb003", "de033btb002"])
# A line that does not say "screened" is not a screening line, whatever else
# it says about TB. It stays in the full list to be chosen by hand.
check("a TB line that is not a screening count is not offered as one",
      any(c["id"] == "de033btb005" for c in ranked["screened"]), False)
check("...but it is still there to be chosen by hand",
      any(c["id"] == "de033btb005" for c in ranked["all"]), True)
check("the AP02 total OPD attendance line is offered first",
      ranked["attendance"][0]["id"], "de033bap02x")
check("...ahead of a line that also says total and also says attendance",
      [c["id"] for c in ranked["attendance"]].index("de033bap0u5") > 0, True)
check("...and ahead of re-attendance",
      [c["id"] for c in ranked["attendance"]].index("de033batt02") > 0, True)
# AP01 here is named "Total OPD Attendance" as well, and would tie on the name
# alone. The AP02 code is what separates them, which is why the code has to
# survive into the ranking rather than being stripped off for display first.
check("...and ahead of the same name under another code",
      [c["id"] for c in ranked["attendance"]].index("de033batt01") > 0, True)
# The whole list stays alphabetical: it is a lookup table, not a ranking, and
# a reader hunting for a line by name needs it where the alphabet says.
check("the full list is still alphabetical, so a line can be found by name",
      ranked["all"][0]["label"], "Children screened for TB among contacts")
metadata._MAPPING["dataElements"] = _SAVED_033B
analytics.reset_cache()

print("\nThe total is cumulative from week 1, not one week")
analytics.reset_cache()
_s = ScreeningSession()
tb = analytics.tb_screening(scope="facility", year=2026, session=_s)
weeks_asked = [d.split(":", 1)[1] for u, p in _s.calls if "analytics" in u
               for d in p["dimension"] if d.startswith("pe:")][0].split(";")
check("it asks from week 1", weeks_asked[0], "2026W1")
check("...through the current week, not the whole year",
      len(weeks_asked), tb["throughWeek"])
# 20 weeks reported at 340 and 85 a week.
check("attendance is the sum of the weeks", tb["attendance"], 20 * 340)
check("screening is the sum of the weeks", tb["screened"], 20 * 85)
check("the two slices partition attendance",
      tb["screened"] + tb["notScreened"], tb["attendance"])
check("the share is screened over attendance", tb["rate"], 25.0)
check("the label says it is a run of weeks",
      tb["periodLabel"].startswith("Weeks 1 to "), True)
check("a recognised pair needs no choice", tb["needsChoice"], False)

print("\nWeeks nobody filed are absent from the total and counted separately")
check("only the weeks that reported are counted", tb["weeksReported"], 20)
check("...and the weeks elapsed are reported alongside",
      tb["weeksElapsed"] >= tb["weeksReported"], True)

print("\nA past year runs to its own last week, not to today's")
analytics.reset_cache()
old = analytics.tb_screening(scope="facility", year=2020, session=ScreeningSession())
check("2020 had 53 ISO weeks", old["throughWeek"], 53)
check("...and its label says the whole of it",
      old["periodLabel"], "Weeks 1 to 53, 2020")

print("\nThe period picker is offered in years, newest first")
_THIS = _date.today().isocalendar()[0]
analytics.reset_cache()
now = analytics.tb_screening(scope="facility", session=ScreeningSession())
check("this year is what is drawn when no year is asked for", now["year"], _THIS)
check("...and it is named as the current one", now["currentYear"], _THIS)
check("the picker offers a run of years", now["years"],
      [_THIS - i for i in range(analytics.SCREENING_YEARS)])
check("...newest first, so the default sits at the top", now["years"][0], _THIS)
check("...and every one of them is a real past year",
      all(y <= _THIS for y in now["years"]), True)
# Every total on this card is cumulative from week 1, so a year IS a period.
# The current one runs to the current week and a past one to its last.
check("this year runs to the current week, not to 52",
      now["throughWeek"], _date.today().isocalendar()[1])

# A year DHIS2 cannot hold data for is refused. Fifty-two weeks of periods
# with nothing behind them draws an empty chart that reads as a hospital which
# filed nothing, and the two want opposite responses from a reader.
for bad in (_THIS + 1, _THIS - analytics.SCREENING_HISTORY - 1):
    try:
        analytics.tb_screening(scope="facility", year=bad, session=ScreeningSession())
        check(f"{bad} is refused", True, False)
    except RuntimeError as exc:
        check(f"{bad} is refused, and the message says the window",
              str(_THIS) in str(exc) and "year parameter" in str(exc), True)

print("\nMore screened than attended cannot be drawn as a slice bigger than the pie")


class BadScreeningSession(ScreeningSession):
    PER_WEEK = {ScreeningSession.ATT: 10, ScreeningSession.SCR: 90}


analytics.reset_cache()
bad = analytics.tb_screening(scope="facility", year=2026, session=BadScreeningSession())
check("the inconsistency is flagged", bad["inconsistent"], True)
check("not-screened never goes negative", bad["notScreened"], 0)

print("\nA year nobody filed is reported as unreported, not as zero screening")


class EmptyScreeningSession(ScreeningSession):
    REPORTED_THROUGH = 0


analytics.reset_cache()
empty = analytics.tb_screening(scope="facility", year=2026, session=EmptyScreeningSession())
check("nothing reported is said so", empty["reported"], False)
check("...and the share is None rather than 0", empty["rate"], None)
check("...and no weeks are claimed", empty["weeksReported"], 0)

print("\nA chosen series is honoured, and a malformed one refused")
analytics.reset_cache()
picked = analytics.tb_screening(scope="facility", year=2026, attendance="de033batt01",
                                screened="de033btb001", session=ScreeningSession())
check("the chosen attendance series is used",
      [e["id"] for e in picked["elements"]["attendance"]], ["de033batt01"])
check("the candidates travel with the figures so the picker can offer them",
      len(picked["candidates"]["attendance"]), 1)
try:
    analytics.tb_screening(attendance="nope", session=ScreeningSession())
    check("a malformed element is refused", True, False)
except RuntimeError as exc:
    check("a malformed element is refused", "Check the parameter" in str(exc), True)

print("\nThe denominator can be several lines, because a total often is")
# Total OPD attendance is new attendance plus re-attendance on this form, so a
# denominator that can only name one line is half a denominator, and a share
# taken against half a denominator reads as twice the truth. That is what a
# screening rate above 100% is made of.
metadata._MAPPING["dataElements"]["HMIS033B"]["de033batt02"] = {
    "name": "033B-AP02. OPD Re-attendance"}


class TwoLineSession(ScreeningSession):
    PER_WEEK = {"de033batt01": 200, "de033batt02": 140, "de033btb001": 255}


analytics.reset_cache()
one = analytics.tb_screening(scope="facility", year=2026, attendance="de033batt01",
                             screened="de033btb001", session=TwoLineSession())
check("one line alone is not the total", one["attendance"], 20 * 200)
check("...so the share comes out over 100%", one["rate"] > 100, True)
check("...and is flagged rather than drawn", one["inconsistent"], True)

analytics.reset_cache()
both = analytics.tb_screening(scope="facility", year=2026,
                              attendance="de033batt01,de033batt02",
                              screened="de033btb001", session=TwoLineSession())
check("both lines add up to the total", both["attendance"], 20 * 340)
check("...and the share is a share again", both["rate"], 75.0)
check("...with the inconsistency gone", both["inconsistent"], False)
check("both elements are named back, in order",
      [e["id"] for e in both["elements"]["attendance"]],
      ["de033batt01", "de033batt02"])
check("the two slices still partition attendance",
      both["screened"] + both["notScreened"], both["attendance"])

# A line named twice is one line. Counting it twice would inflate the very
# total it is meant to describe, and silently halve the share.
analytics.reset_cache()
dup = analytics.tb_screening(scope="facility", year=2026,
                             attendance="de033batt01,de033batt01,de033batt02",
                             screened="de033btb001", session=TwoLineSession())
check("a repeated line is counted once", dup["attendance"], 20 * 340)

try:
    analytics.tb_screening(attendance="de033batt01,nope", session=TwoLineSession())
    check("one bad id in a list is refused, not skipped", True, False)
except RuntimeError as exc:
    check("one bad id in a list is refused, not skipped", "'nope'" in str(exc), True)

del metadata._MAPPING["dataElements"]["HMIS033B"]["de033batt02"]
analytics.reset_cache()

print("\nThe outer ring is 105:01 attendance by age band, cumulative from January")
metadata._MAPPING["HMIS105_01_codeIndex"] = {"OA01": "sv6SeKroHPV", "OA02": "sQ4EexvvhVe"}
metadata._MAPPING["categoryCombos"] = {"OPD_AGE_SEX": {"id": "esaNB4G5AHs", "cocs": {
    "0-28Dys, Male": "coc0028m001", "0-28Dys, Female": "coc0028f001",
    "29Dys-4Yrs, Male": "coc29d4ym01", "29Dys-4Yrs, Female": "coc29d4yf01",
    "5-9Yrs, Male": "coc59yrsm01", "5-9Yrs, Female": "coc59yrsf01",
    "10-19Yrs, Male": "coc1019m001", "10-19Yrs, Female": "coc1019f001",
    "20+Yrs, Male": "coc20plm001", "20+Yrs, Female": "coc20plf001",
}}}


class AgeSession(StubSession):
    """105:01 attendance, ten combos a month, plus one combo this build has
    never heard of."""

    PER_COMBO = 12

    def _analytics(self, params):
        dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in params.get("dimension", [])
                if ":" in d}
        combos = list(metadata._MAPPING["categoryCombos"]["OPD_AGE_SEX"]["cocs"].values())
        rows = []
        for pe in dims.get("pe", "").split(";"):
            for dx in dims.get("dx", "").split(";"):
                for co in combos + ["cocUNKNOWN1"]:
                    rows.append([dx, pe, dims["ou"], co, str(self.PER_COMBO)])
        return {"headers": [{"name": "dx"}, {"name": "pe"}, {"name": "ou"},
                            {"name": "co"}, {"name": "value"}],
                "metaData": {"items": {}}, "rows": rows}


analytics.reset_cache()
_a = AgeSession()
prof = analytics.attendance_by_age(scope="facility", year=2026, session=_a)
call = [p for u, p in _a.calls if "analytics" in u][0]
check("the combo dimension is asked for", "co" in call["dimension"], True)
pe = [d for d in call["dimension"] if d.startswith("pe:")][0].split(":", 1)[1].split(";")
check("it asks from January", pe[0], "202601")
check("...in months, because 105:01 is monthly", len(pe[0]), 6)
check("all five age bands are returned", [b["band"] for b in prof["bands"]],
      analytics.AGE_BAND_ORDER)
# Two sexes x two elements x len(pe) months x 12 each.
per_band = 2 * 2 * len(pe) * AgeSession.PER_COMBO
check("male and female fold into one age band", prof["bands"][0]["value"], per_band)
check("a combo this build does not know is counted, not dropped",
      prof["unclassified"], 2 * len(pe) * AgeSession.PER_COMBO)
check("the total includes it", prof["total"], per_band * 5 + prof["unclassified"])
check("the band labels are readable", prof["bands"][0]["label"], "0 to 28 days")

print("\nThe two rings are separate wholes and say which period each covers")
analytics.reset_cache()
both = analytics.tb_screening(scope="facility", year=2026, session=AgeSession())
check("the age profile travels with the screening figures",
      both["ageProfile"]["available"], True)
check("the inner ring is counted in weeks", both["periodLabel"].startswith("Weeks 1 to "), True)
check("...and the outer ring in months",
      both["ageProfile"]["periodLabel"].startswith("January to "), True)

print("\n105:01 being unreadable does not stop the screening split drawing")


class NoAgeSession(ScreeningSession):
    pass


metadata._MAPPING["categoryCombos"] = {}
analytics.reset_cache()
without = analytics.tb_screening(scope="facility", year=2026, session=NoAgeSession())
check("the outer ring is simply absent", without["ageProfile"]["available"], False)
check("...and the inner ring still has its figures", without["attendance"], 20 * 340)

print("\nA name the matcher does not recognise offers a choice, not a dead end")
# The real 033B names differ between instances and form revisions. Refusing to
# draw anything, and telling the operator to refresh metadata they already
# have, sends them to fix something that is not broken.
metadata._MAPPING["dataElements"] = {"HMIS033B": {
    "de033bxxx01": {"name": "033B-AP01. Persons seen this week"},
    "de033bxxx02": {"name": "033B-AP02. Presumptive TB investigated"},
}}
analytics.reset_cache()
odd = analytics.tb_screening(scope="facility", year=2026, session=ScreeningSession())
check("it does not raise", isinstance(odd, dict), True)
check("it says a choice is needed", odd["needsChoice"], True)
check("...and offers every cached element to choose from",
      len(odd["candidates"]["all"]), 2)
check("...naming how many are cached", odd["candidates"]["cached"], 2)
check("no figure is invented from an unconfirmed element", odd["attendance"], None)
check("...and the share is withheld too", odd["rate"], None)
check("which series matched is reported", odd["matched"],
      {"attendance": False, "screened": False})

print("\nA chosen pair is honoured even when the matcher recognised neither")
analytics.reset_cache()
fixed = analytics.tb_screening(scope="facility", year=2026, attendance="de033bxxx01",
                               screened="de033bxxx02", session=ScreeningSession())
check("choosing both resolves it", fixed["needsChoice"], False)
check("the chosen attendance element is used",
      [e["id"] for e in fixed["elements"]["attendance"]], ["de033bxxx01"])

print("\nThe four 033B death lines resolve by code first, then by name")
# A code survives a reworded name, and these four are reworded often: "Fresh
# Still Birth" and "Fresh stillbirths" are the same line of the same form. So
# CD22 here is named nothing like the register names it, and must still
# resolve; CD23 carries no code at all, and must resolve by its name.
metadata._MAPPING["dataElements"] = {"HMIS033B": {
    "de033bcd20": {"name": "033B-CD20. Maternal death", "code": "CD20"},
    "de033bcd21": {"name": "033B-CD21. Macerated Still births", "code": "CD21"},
    "de033bcd22": {"name": "033B-CD22. Stillbirth, fresh", "code": "CD22"},
    "de033bcd23": {"name": "033B-CD23. Early Neonatal deaths 0-7 days"},
    "de033bmal01": {"name": "033B-CD01a. Malaria (Confirmed) - Cases", "code": "CD01a"},
}}
metadata._MAPPING["HMIS033B_codeIndex"] = {
    "CD20": "de033bcd20", "CD21": "de033bcd21", "CD22": "de033bcd22",
    "CD01a": "de033bmal01",
}
analytics.reset_cache()
resolved = analytics.death_lines()
check("all four lines are offered, in the order the form prints them",
      [l["code"] for l in resolved], ["CD20", "CD21", "CD22", "CD23"])
check("...carrying the abbreviation the paper register uses",
      [l["short"] for l in resolved], ["MD", "MB", "FB", "EN"])
check("a line resolves by its code even when renamed",
      next(l["id"] for l in resolved if l["code"] == "CD22"), "de033bcd22")
check("...and by its name when it carries no code",
      next(l["id"] for l in resolved if l["code"] == "CD23"), "de033bcd23")
check("an unrelated 033B line is not mistaken for one of them",
      any(l["id"] == "de033bmal01" for l in resolved), False)


class DeathSession(StubSession):
    """Three deaths a week on two lines, none on a third, over 20 weeks."""

    PER_WEEK = {"de033bcd20": 1, "de033bcd21": 2, "de033bcd22": 0, "de033bcd23": 3}
    REPORTED_THROUGH = 20

    def _analytics(self, params):
        dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in params.get("dimension", [])}
        rows = []
        for pe in dims.get("pe", "").split(";"):
            m = _re.fullmatch(r"(\d{4})W(\d{1,2})", pe)
            if not m or int(m.group(2)) > self.REPORTED_THROUGH:
                continue
            for dx in dims["dx"].split(";"):
                if dx in self.PER_WEEK:
                    rows.append([dx, pe, dims["ou"], str(self.PER_WEEK[dx])])
        return {"headers": [{"name": "dx"}, {"name": "pe"}, {"name": "ou"}, {"name": "value"}],
                "metaData": {"items": {}}, "rows": rows}


analytics.reset_cache()
deaths = analytics.perinatal_deaths(scope="facility", year=2026, session=DeathSession())
by_code = {l["code"]: l for l in deaths["lines"]}
check("each line is the sum of its weeks", by_code["CD20"]["value"], 20 * 1)
check("...for every line", by_code["CD23"]["value"], 20 * 3)
# Zero is a claim: nobody died on this line in the weeks that were filed.
check("a line with no deaths reads zero, not blank", by_code["CD22"]["value"], 0)
check("the total counts only the lines that resolved",
      deaths["total"], 20 * (1 + 2 + 0 + 3))
_W26 = _date.today().isocalendar()[1] if _date.today().isocalendar()[0] == 2026 \
    else analytics.iso_weeks_in_year(2026)
check("the period is a run of weeks, like the rest of the row",
      deaths["periodLabel"], f"Weeks 1 to {_W26}, 2026")
check("only the weeks that reported are counted", deaths["weeksReported"], 20)
check("...against the weeks elapsed, which is not the same number",
      (deaths["weeksElapsed"], deaths["weeksElapsed"] > deaths["weeksReported"]),
      (_W26, True))

print("\nA death line the form does not carry is blank, never zero")
# Nobody died and nobody knows are opposite claims. A tile printing 0 for both
# would report a clean week on a line the instance cannot even see.
metadata._MAPPING["dataElements"] = {"HMIS033B": {
    "de033bcd20": {"name": "033B-CD20. Maternal death", "code": "CD20"},
}}
metadata._MAPPING["HMIS033B_codeIndex"] = {"CD20": "de033bcd20"}
analytics.reset_cache()
partial = analytics.perinatal_deaths(scope="facility", year=2026, session=DeathSession())
part_by = {l["code"]: l for l in partial["lines"]}
check("the line that resolved carries a figure", part_by["CD20"]["value"], 20)
check("the ones that did not are None, not 0", part_by["CD21"]["value"], None)
check("...and are still listed so the gap is visible",
      [l["code"] for l in partial["lines"]], ["CD20", "CD21", "CD22", "CD23"])
check("how many resolved is reported", partial["resolved"], 1)

metadata._MAPPING["dataElements"] = {"HMIS033B": {}}
metadata._MAPPING["HMIS033B_codeIndex"] = {}
analytics.reset_cache()
none = analytics.perinatal_deaths(scope="facility", year=2026, session=DeathSession())
check("no line at all does not raise", isinstance(none, dict), True)
check("...and no total is invented", none["total"], None)
check("...and nothing is claimed to have reported", none["reported"], False)

try:
    analytics.perinatal_deaths(scope="planet", session=DeathSession())
    check("an unknown scope is refused", True, False)
except RuntimeError as exc:
    check("an unknown scope is refused", "Check the scope parameter" in str(exc), True)

print("\nInpatient deaths are measured against admissions, both from 108")
# CI03 over CI02 is a ratio the form supports: both are the monthly inpatient
# return, counted on the same line of the same register. Deaths over OPD
# attendances, which this card used to show, divides a ward number by a door
# number and cannot be checked against any standard.
metadata._MAPPING["dataElements"] = {"HMIS108": {
    "de108ci02x": {"name": "108-CI02. No. of admissions", "code": "CI02"},
    "de108ci03x": {"name": "108-CI03. No. of deaths", "code": "CI03"},
    "de108ci01x": {"name": "108-CI01. No. of beds", "code": "CI01"},
}}
metadata._MAPPING["HMIS108_codeIndex"] = {
    "CI02": "de108ci02x", "CI03": "de108ci03x", "CI01": "de108ci01x"}


class InpatientSession(StubSession):
    """Three months: one under the standard, one over, one with no admissions."""

    # month -> (admissions, deaths)
    BY_MONTH = {1: (600, 18), 2: (500, 30), 3: (0, 0)}

    def _analytics(self, params):
        dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in params.get("dimension", [])}
        rows = []
        for pe in dims.get("pe", "").split(";"):
            m = _re.fullmatch(r"(\d{4})(\d{2})", pe)
            if not m or int(m.group(2)) not in self.BY_MONTH:
                continue
            adm, dea = self.BY_MONTH[int(m.group(2))]
            for dx in dims["dx"].split(";"):
                if dx == "de108ci02x":
                    rows.append([dx, pe, dims["ou"], str(adm)])
                elif dx == "de108ci03x":
                    rows.append([dx, pe, dims["ou"], str(dea)])
        return {"headers": [{"name": "dx"}, {"name": "pe"}, {"name": "ou"}, {"name": "value"}],
                "metaData": {"items": {}}, "rows": rows}


analytics.reset_cache()
ip = analytics.inpatient_mortality(scope="facility", year=2026, session=InpatientSession())
check("the standard is 4% of admissions", ip["standard"], 4.0)
check("the two elements are named back",
      [ip["elements"]["admissions"]["code"], ip["elements"]["deaths"]["code"]],
      ["CI02", "CI03"])
months = {m["month"]: m for m in ip["months"]}
check("a month's rate is its deaths over its admissions", months[1]["rate"], 3.0)
check("...and a month over the standard is flagged", months[2]["rate"], 6.0)
check("...as over", months[2]["overStandard"], True)
check("...while one under it is not", months[1]["overStandard"], False)
# Zero admissions is no denominator. Drawn as 0% it would read as the best
# month of the year, which is the opposite of what an empty month means.
check("a month with no admissions has no rate", months[3]["rate"], None)
check("...and is not counted as over the standard", months[3]["overStandard"], False)
check("the headline rate is the year's deaths over the year's admissions",
      ip["rate"], round(100 * 48 / 1100, 2))
# 4.36% over the year, from one month at 3% and one at 6%. The verdict is on
# the year's own ratio, not on an average of the months: a small month at a
# terrible rate must not weigh the same as a large one at a good rate.
check("...and the verdict is on that ratio", ip["withinStandard"], False)
check("months over the standard are counted separately",
      ip["monthsOverStandard"], 1)
check("the raw counts travel with the rate so it can be checked",
      (ip["deaths"], ip["admissions"]), (48, 1100))

class GoodYearSession(InpatientSession):
    BY_MONTH = {1: (600, 18), 2: (500, 15)}


analytics.reset_cache()
good = analytics.inpatient_mortality(scope="facility", year=2026, session=GoodYearSession())
check("a year inside the standard says so", good["withinStandard"], True)
check("...with no month over it", good["monthsOverStandard"], 0)

print("\nA rate with no elements behind it is withheld, not drawn as zero")
metadata._MAPPING["dataElements"] = {"HMIS108": {}}
metadata._MAPPING["HMIS108_codeIndex"] = {}
analytics.reset_cache()
bare = analytics.inpatient_mortality(scope="facility", year=2026, session=InpatientSession())
check("it does not raise", isinstance(bare, dict), True)
check("...and says the elements did not resolve", bare["resolved"], False)
check("...and invents no rate", bare["rate"], None)
check("...nor a verdict against the standard", bare["withinStandard"], None)
check("...and still names the standard it would have used", bare["standard"], 4.0)

try:
    analytics.inpatient_mortality(scope="facility", year=_date.today().year + 1,
                                  session=InpatientSession())
    check("a year that has not happened is refused", True, False)
except RuntimeError as exc:
    check("a year that has not happened is refused",
          "Check the year parameter" in str(exc), True)

print("\nAn empty 033B listing is the one case that really is a metadata problem")
metadata._MAPPING["HMIS033B_codeIndex"] = {}
metadata._MAPPING["HMIS108_codeIndex"] = {}
metadata._MAPPING["dataElements"] = {}
analytics.reset_cache()
try:
    analytics.tb_screening(session=ScreeningSession())
    check("an empty listing raises", True, False)
except RuntimeError as exc:
    check("an empty listing raises", "Refresh metadata" in str(exc), True)
    check("...and says the list is empty, not that a name was unmatched",
          "element list is empty" in str(exc), True)

print("\nRows are read by header name, not by position")
# Analytics puts the columns in whatever order the dimensions were given. A
# reader that assumed dx/pe/ou/value would silently transpose two fields.
shuffled = {
    "headers": [{"name": "ou"}, {"name": "value"}, {"name": "dx"}, {"name": "pe"}],
    "rows": [["ouX", "17", "dxX", "202607"]],
}
row = analytics._rows(shuffled)[0]
check("value is read from its named column", row["value"], "17")
check("dx is read from its named column", row["dx"], "dxX")
check("ou is read from its named column", row["ou"], "ouX")

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
