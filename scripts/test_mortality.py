"""Counting deaths, and not counting anything else.

Two things are being defended here.

THE ARITHMETIC. A death rate is the one figure on this dashboard that a
clinician might quote in a meeting, so the denominator has to be the one the
label claims: attendances for the week asked about, from that week's own
return, never a window average.

THE PRIVACY. A medical certificate of cause of death names the deceased. It
also carries an inpatient number, a village, an age and a religion. This module
reads certificates in order to count them, and the fixture below hands it an
event carrying every one of those fields; the checks assert that none of them
survives into what the endpoint returns. The tally is all that leaves.

    python scripts/test_mortality.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import metadata  # noqa: E402

metadata._MAPPING = {
    **metadata.CONSTANTS,
    "dataElements": {"HMIS105_01": {}, "HMIS108": {}, "HMIS033B": {}},
    "HMIS105_01_codeIndex": {}, "HMIS108_codeIndex": {},
    "HMIS033B_codeIndex": {"AP01": "de_ap01", "AP02": "de_ap02", "AP03": "de_ap03"},
}

from _lib import analytics, mortality  # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


FACILITY = metadata.CONSTANTS["orgUnit"]["id"]

# One certificate as DHIS2 returns it: two fields this module wants, and five it
# must not keep. The names are invented; the field list is the real one.
IDENTIFIERS = {
    "hL9k1nAmE01": "NAMUKOSE ESTHER",
    "hL9k1nInP02": "IP/2026/04417",
    "hL9k1nVil03": "BUNENA VILLAGE, KAMULI",
    "hL9k1nAge04": "32",
    "hL9k1nRel05": "Roman Catholic",
}


def event(cause, contributed=None, pregnant=None, stillborn=None):
    values = [{"dataElement": k, "value": v} for k, v in IDENTIFIERS.items()]
    if cause is not None:
        values.append({"dataElement": mortality.UNDERLYING_CAUSE, "value": cause})
    if contributed is not None:
        values.append({"dataElement": mortality.PREGNANCY_CONTRIBUTED, "value": contributed})
    if pregnant is not None:
        values.append({"dataElement": mortality.WAS_PREGNANT, "value": pregnant})
    if stillborn is not None:
        values.append({"dataElement": mortality.STILLBORN, "value": stillborn})
    return {"event": "ev123", "orgUnit": FACILITY, "occurredAt": "2026-08-20",
            "dataValues": values}


# The window's certificates. Birth asphyxia leads; three of the deaths are ones
# a pregnancy contributed to, which is what the maternal bars are drawn from.
EVENTS = (
    [event("BIRTH ASPHYXIA, UNSPECIFIED") for _ in range(11)]
    + [event("ESSENTIAL HYPERTENSION, UNSPECIFIED") for _ in range(8)]
    + [event("UNSPECIFIED MULTIPLE INJURIES") for _ in range(8)]
    + [event("PNEUMONITIS DUE TO INHALATION OF FOOD OR VOMIT") for _ in range(6)]
    + [event("HIV DISEASE CLINICAL STAGE 4 ASSOCIATED WITH TUBERCULOSIS") for _ in range(3)]
    + [event("ALCOHOLIC LIVER DISEASE, UNSPECIFIED") for _ in range(2)]
    + [event("ANAEMIAS OR OTHER ERYTHROCYTE DISORDERS, UNSPECIFIED", contributed="Yes") for _ in range(3)]
    + [event("HYPOVOLAEMIC SHOCK", contributed="Yes") for _ in range(2)]
    + [event("PRE-ECLAMPSIA, UNSPECIFIED", contributed="Yes")]
    + [event("APH", contributed="yes")]
    + [event("SEVERE ANAEMIA", pregnant="Yes")]        # pregnant, but not a contributor
    # The perinatal half of MPDSR: stillbirths, which the certificate flags
    # separately from the maternal question.
    + [event("BIRTH ASPHYXIA, UNSPECIFIED", stillborn="Yes") for _ in range(3)]
    + [event("UNKNOWN", stillborn="Yes") for _ in range(2)]
    + [event(None), event("   ")]                       # certified with no cause
)

SEEN, DEATHS = 2103, 2


class Response:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


class Session:
    def __init__(self, events=None, status=200):
        self.events = EVENTS if events is None else events
        self.status = status
        self.event_params = None

    def get(self, url, params=None, timeout=None):
        if "/programs.json" in url:
            return Response({"programs": [
                {"id": "otherProg1", "name": "HMIS 016 - Maternal Perinatal Death Review"},
                {"id": "mccodProg1", "name": "HMIS 100 - Medical Certificate of Cause of Death"},
            ]})
        if "/organisationUnits/" in url:
            return Response({"id": FACILITY, "name": "Jinja Regional Referral Hospital",
                             "level": 6, "ancestors": [
                                 {"id": "nationUID1", "name": "Uganda", "level": 1},
                                 {"id": "regionUID1", "name": "Busoga Region", "level": 2}]})
        if "/tracker/events" in url:
            self.event_params = params
            if self.status != 200:
                return Response({}, self.status)
            return Response({"instances": self.events})
        if "/analytics.json" in url:
            dims = {d.split(":", 1)[0]: d.split(":", 1)[1] for d in params["dimension"]}
            rows = []
            for dx in dims["dx"].split(";"):
                value = {"de_ap02": SEEN, "de_ap01": 2060, "de_ap03": DEATHS}.get(dx)
                if value is not None:
                    rows.append([dx, dims["pe"], dims["ou"], str(value)])
            return Response({"headers": [{"name": "dx"}, {"name": "pe"}, {"name": "ou"},
                                         {"name": "value"}],
                             "rows": rows, "metaData": {"items": {}}})
        raise AssertionError(f"unexpected request: {url}")


def summary(**kw):
    analytics.reset_cache()
    return mortality.summary(period="2026W34", session=Session(**kw))


print("\n-- an ICD-11 term, as a chart axis can carry it --")
check("the trailing qualifier goes", mortality.tidy_cause("ESSENTIAL HYPERTENSION, UNSPECIFIED"),
      "Essential hypertension")
check("...and 'not elsewhere classified' with it",
      mortality.tidy_cause("OTHER SEPSIS, NOT ELSEWHERE CLASSIFIED"), "Other sepsis")
check("an abbreviation is left alone", mortality.tidy_cause("APH"), "APH")
check("...even inside a term",
      mortality.tidy_cause("HIV DISEASE CLINICAL STAGE 4"), "HIV disease clinical stage 4")
check("the term itself is never reworded",
      mortality.tidy_cause("PNEUMONITIS DUE TO INHALATION OF FOOD OR VOMIT"),
      "Pneumonitis due to inhalation of food or vomit")
check("blank stays blank", mortality.tidy_cause("   "), "")
check("None stays blank", mortality.tidy_cause(None), "")

print("\n-- the five leading causes --")
data = summary()
check("five bars, not six", len(data["allCause"]), 5)
check("ordered by deaths",
      [r["deaths"] for r in data["allCause"]], [14, 8, 8, 6, 3])
check("the leading cause", data["allCause"][0],
      {"cause": "Birth asphyxia", "deaths": 14})
check("a tie is broken by name, so the order never wobbles between reloads",
      [r["cause"] for r in data["allCause"][1:3]],
      ["Essential hypertension", "Unspecified multiple injuries"])
check("the count is of certificates that carry a cause", data["certifiedInWindow"], 51)
check("...out of every certificate read", data["eventsRead"], 53)

print("\n-- and the MPDSR ones, which are both halves --")
check("deaths a pregnancy contributed to", data["maternalInWindow"], 7)
check("...and stillbirths", data["perinatalInWindow"], 5)
check("...counted together, because that is what MPDSR means",
      data["mpdsrInWindow"], 12)
check("both halves are in the same ranking, tied at three and ordered by name",
      [(r["cause"], r["deaths"]) for r in data["mpdsr"][:2]],
      [("Anaemias or other erythrocyte disorders", 3), ("Birth asphyxia", 3)])
check("the maternal causes are in the same group",
      any(r["cause"] == "Anaemias or other erythrocyte disorders" for r in data["mpdsr"]), True)
check("...case-insensitively, because the form stores what was typed",
      any(r["cause"] == "APH" for r in data["mpdsr"]), True)
check("a pregnancy that did not contribute is neither",
      any(r["cause"] == "Severe anaemia" for r in data["mpdsr"]), False)
check("a recorded 'unknown' is shown rather than quietly dropped",
      any(r["cause"] == "Unknown" for r in data["mpdsr"]), True)

print("\n-- the rate, and what it is made of --")
check("patients seen", data["seen"], SEEN)
check("deaths", data["deaths"], DEATHS)
check("per thousand attendances", data["ratePerThousand"], round(2 / 2103 * 1000, 2))
check("the denominator is named", data["denominatorSource"], "033B attendance (AP02)")
check("the period asked for is the period reported", data["period"], "2026W34")
check("...and the window behind the bars is named", data["window"]["label"], "Since 1 January")
check("...year to date by default", data["window"]["from"], "2026-01-01")
check("...with the alternatives offered",
      [w["key"] for w in data["windows"]], ["ytd", "13w", "12m", "24m"])
thirteen = mortality.summary(period="2026W34", window="13w", session=Session())
check("a shorter window starts thirteen weeks before the period ends",
      thirteen["window"]["from"], "2026-05-24")
try:
    mortality.summary(period="2026W34", window="fortnight", session=Session())
    check("an unknown window is refused", "no error", "RuntimeError")
except RuntimeError as exc:
    check("an unknown window is refused", "Use one of" in str(exc), True)
no_deaths = mortality.summary(period="2026W34", session=Session(events=[]))
check("no certificates means no bars, not a zero", no_deaths["allCause"], [])
check("...on both groups", no_deaths["mpdsr"], [])
check("...and the rate still stands, because it does not come from certificates",
      no_deaths["ratePerThousand"], round(2 / 2103 * 1000, 2))

print("\n-- nothing but the tally leaves this module --")
serialised = json.dumps(summary())
for field, value in IDENTIFIERS.items():
    check(f"the certificate's {value.split()[0].lower()[:12]} field is not in the payload",
          value in serialised or field in serialised, False)
check("no event id either", "ev123" in serialised, False)
check("no raw dataValues", "dataValues" in serialised, False)

print("\n-- the request that was sent --")
s = Session()
analytics.reset_cache()
mortality.summary(period="2026W34", session=s)
check("events are asked for by program", s.event_params["program"], "mccodProg1")
check("...for this hospital only", (s.event_params["orgUnit"], s.event_params["ouMode"]),
      (FACILITY, "SELECTED"))
check("...and only the data values are requested, never the names beside them",
      s.event_params["fields"], "dataValues[dataElement,value]")
check("the window ends with the period asked about",
      s.event_params["occurredBefore"] >= "2026-08-24", True)

print("\n-- the card names the two groups as the programme does --")
with open(os.path.join(HERE, "..", "app", "mortality.js")) as fh:
    card = fh.read()
check("all-cause", "All Cause Mortality" in card, True)
check("MPDSR, spelled out", "Maternal and Perinatal Death Surveillance and Response" in card, True)
check("...and the split is shown beside it, so the heading is not a claim the "
      "bars cannot support",
      "maternal, " in card and "perinatal" in card, True)

print("\n-- when DHIS2 says no --")
try:
    mortality.summary(period="2026W34", session=Session(status=403))
    check("a refusal is explained, not swallowed", "no error", "RuntimeError")
except RuntimeError as exc:
    check("a refusal is explained, not swallowed", "HMIS 100" in str(exc), True)
try:
    mortality.summary(period="not-a-period", session=Session())
    check("a nonsense period is refused", "no error", "RuntimeError")
except RuntimeError as exc:
    check("a nonsense period is refused", "ISO week" in str(exc), True)

print(f"\n{len(failures)} failed")
for f in failures:
    print(" ", f)
sys.exit(1 if failures else 0)
