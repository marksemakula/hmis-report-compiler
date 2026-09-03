"""The malaria channel's arithmetic, offline.

The channel decides whether a week is an epidemic. That makes its arithmetic
the most consequential in this application: everything else reports what a
register already said, while this asserts something new about the week.

The thresholds are not this project's invention and must not drift into it.
Uganda's evaluation of outbreak-detection methods (Malaria Journal, 2024)
compared the 75th percentile, mean + 2SD and C-SUM on five years of DHIS2 data
and recommended the 75th percentile for detection in all areas; UNIPH's policy
brief adds the 85th as the epidemic threshold. The lower limit is the 25th, the
mirror of the upper - there is no Ugandan guidance for a floor, and the older
lowest-of-five-years convention is fragile here: one stock-out week, or one week
the return was not filed, would hold the floor near zero for five years.

    python scripts/test_channel.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import metadata  # noqa: E402

DE = "de_malaria_cases"
metadata._MAPPING = {
    **metadata.CONSTANTS,
    "dataElements": {
        "HMIS105_01": {}, "HMIS108": {},
        "HMIS033B": {DE: {"name": "033B-MA01a. Malaria - Cases", "code": "MA01a",
                          "categoryCombo": "cc", "zeroIsSignificant": False}},
    },
    "HMIS105_01_codeIndex": {}, "HMIS108_codeIndex": {}, "HMIS033B_codeIndex": {},
}

from _lib import analytics  # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


# --------------------------------------------------------------- the fixture
#
# Week 10 carries the five baseline years 100, 120, 140, 160, 300 in that
# order, chosen so every limit lands on a different number and an interpolated
# percentile cannot be confused with an observation:
#
#     25th = 120     50th = 140     75th = 160     85th = 216
#
# Week 20 is flat at 50 in every year, the case where all four limits coincide.
# Week 30 was reported in only two of the five years, which is what a channel
# built on a thin baseline looks like.
BASELINE = {
    10: [100, 120, 140, 160, 300],
    20: [50, 50, 50, 50, 50],
    30: [80, 90],
}
CURRENT = {10: 500, 20: 50, 30: 85}
YEAR = 2026
BASE_YEARS = [2021, 2022, 2023, 2024, 2025]

FACILITY = metadata.CONSTANTS["orgUnit"]["id"]
REGION, NATIONAL, PEER = "regionUID01", "nationUID1", "peerFacil01"


class Response:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


class Session:
    """Answers the three calls the channel makes, and records them."""

    def __init__(self):
        self.analytics_calls = []

    def get(self, url, params=None, timeout=None):
        if "/organisationUnits.json" in url:
            return Response({"organisationUnits": [
                {"id": PEER, "name": "Buwenge HC IV"},
                {"id": "peerFacil02", "name": "Kamuli General Hospital"},
            ]})
        if "/organisationUnits/" in url:
            return Response({
                "id": FACILITY, "name": "Jinja Regional Referral Hospital", "level": 6,
                "ancestors": [
                    {"id": NATIONAL, "name": "Uganda", "level": 1},
                    {"id": REGION, "name": "Busoga Region", "level": 2},
                    {"id": "districtUI", "name": "Jinja District", "level": 3},
                ],
            })
        if "/analytics.json" in url:
            self.analytics_calls.append(params)
            dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in params["dimension"]}
            ou, rows = dims["ou"], []
            for pe in dims["pe"].split(";"):
                year, week = int(pe[:4]), int(pe[5:])
                if week not in BASELINE:
                    continue
                if year == YEAR:
                    value = CURRENT[week]
                elif year in BASE_YEARS[-len(BASELINE[week]):]:
                    value = BASELINE[week][BASE_YEARS.index(year)
                                           - (5 - len(BASELINE[week]))]
                else:
                    continue
                # A peer facility reports half of what this hospital does, so a
                # channel drawn for the wrong org unit is visible in the values.
                rows.append([DE, pe, ou, str(value // 2 if ou == PEER else value)])
            return Response({
                "headers": [{"name": "dx"}, {"name": "pe"}, {"name": "ou"}, {"name": "value"}],
                "rows": rows,
                "metaData": {"items": {}},
            })
        raise AssertionError(f"unexpected request: {url}")


def channel(**kw):
    analytics.reset_cache()
    return analytics.malaria_channel(year=YEAR, session=Session(), **kw)


print("\n-- the percentile itself --")
five = [100, 120, 140, 160, 300]
check("25th of the fixture", analytics._percentile(five, 25), 120.0)
check("50th", analytics._percentile(five, 50), 140.0)
check("75th", analytics._percentile(five, 75), 160.0)
check("85th interpolates between the top two", analytics._percentile(five, 85), 216.0)
check("a single year is its own percentile", analytics._percentile([7], 25), 7.0)
check("no history has no percentile", analytics._percentile([], 25), None)
check("the low percentile is the mirror of the alert",
      analytics.LOW_PERCENTILE + analytics.ALERT_PERCENTILE, 100)

print("\n-- the limits Uganda's guidance names --")
check("alert is the 75th", analytics.ALERT_PERCENTILE, 75)
check("epidemic is the 85th", analytics.EPIDEMIC_PERCENTILE, 85)
check("the floor is the 25th", analytics.LOW_PERCENTILE, 25)
check("five years of baseline", analytics.MIN_BASELINE_YEARS, 5)

print("\n-- a week's four limits --")
data = channel()
w10 = next(w for w in data["weeks"] if w["week"] == 10)
check("lower limit", w10["low"], 120.0)
check("median", w10["median"], 140.0)
check("upper limit", w10["alert"], 160.0)
check("epidemic line", w10["epidemic"], 216.0)
check("the extremes are carried for the tooltip", (w10["min"], w10["max"]), (100, 300))
check("this year's figure", w10["current"], 500)
check("the limits never cross",
      w10["low"] <= w10["median"] <= w10["alert"] <= w10["epidemic"], True)
check("the percentiles used are declared in the payload",
      (data["lowPercentile"], data["alertPercentile"], data["epidemicPercentile"]),
      (25, 75, 85))

w20 = next(w for w in data["weeks"] if w["week"] == 20)
check("a flat baseline collapses the channel to one value",
      (w20["low"], w20["median"], w20["alert"], w20["epidemic"]), (50.0, 50.0, 50.0, 50.0))

w30 = next(w for w in data["weeks"] if w["week"] == 30)
check("a thin baseline still yields limits", (w30["n"], w30["low"]), (2, 82.5))
w40 = next(w for w in data["weeks"] if w["week"] == 40)
check("a week with no history has none of them",
      [w40["low"], w40["median"], w40["alert"], w40["epidemic"]], [None, None, None, None])

print("\n-- where the latest week sits --")


def status_for(latest_value):
    CURRENT[30] = latest_value
    try:
        return channel()["status"]
    finally:
        CURRENT[30] = 85


check("above the epidemic line", status_for(500), "epidemic")
check("between alert and epidemic", status_for(88), "alert")
check("inside the channel", status_for(85), "normal")
check("below the lower limit", status_for(10), "low")
# A quiet week is a data-quality question, not an outbreak, and the chart must
# not colour it like one.
with open(os.path.join(HERE, "..", "app", "malariachannel.js")) as fh:
    component = fh.read()
low_entry = component[component.index("  low: {"):component.index("\n", component.index("  low: {"))]
check("a week below the floor is styled as muted, not as a fault",
      "'muted'" in low_entry and "'bad'" not in low_entry, True)
check("...and the component reads the same floor the server sends",
      "Lower limit (25th percentile)" in component, True)

print("\n-- which organisation unit was charted --")
check("the default is this hospital", data["orgUnit"]["id"], FACILITY)
check("...and it is labelled as the facility scope", data["scope"], "facility")
region = channel(scope="region")
check("the region can be asked for", region["orgUnit"]["id"], REGION)
check("...and says so", region["scope"], "region")
national = channel(scope="national")
check("the country too", (national["orgUnit"]["id"], national["scope"]),
      (NATIONAL, "national"))

peer = channel(ou=PEER)
check("a named facility overrides the scope", peer["orgUnit"]["name"], "Buwenge HC IV")
check("...and is reported as neither of the three scopes", peer["scope"], "other")
peer10 = next(w for w in peer["weeks"] if w["week"] == 10)
check("...and its own figures are charted, not this hospital's",
      (peer10["current"], peer10["alert"]), (250, 80.0))

print("\n-- an organisation unit that is not ours to chart --")
try:
    channel(ou="notAfacility")
    check("an unknown org unit is refused", "no error", "RuntimeError")
except RuntimeError as exc:
    check("an unknown org unit is refused", isinstance(exc, RuntimeError), True)
    check("...and the message names the region",
          "Busoga Region" in str(exc), True)
    check("...and says what can be charted instead",
          "any facility in the regional list" in str(exc), True)

print("\n-- the request that was actually sent --")
s = Session()
analytics.reset_cache()
analytics.malaria_channel(year=YEAR, session=s)
pes = [d for call in s.analytics_calls for d in call["dimension"] if d.startswith("pe:")]
check("six years are requested: five baseline and this one", len(pes), 6)
check("weeks are asked for as ISO week periods",
      all(p.startswith("pe:2") and "W" in p for p in pes), True)
check("2026 is asked for all 53 of its ISO weeks",
      len([p for p in pes if "2026W" in p][0].split(";")), 53)
check("2025 has 52", len([p for p in pes if "2025W" in p][0].split(";")), 52)

print(f"\n{len(failures)} failed")
for f in failures:
    print(" ", f)
sys.exit(1 if failures else 0)
