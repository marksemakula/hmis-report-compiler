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
