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
