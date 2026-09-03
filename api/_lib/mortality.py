"""Deaths at this hospital: how many, against how many patients, and of what.

WHERE THE CAUSES ACTUALLY ARE

The obvious places are empty. HMIS 108 carries 249 cause-of-death elements,
one per condition, and at Jinja every one of them is blank; the only death
figure the inpatient return holds is CI03, disaggregated by ward rather than by
cause. 033B has 48 weekly death lines, of which week 34 of 2026 carried exactly
one. The Maternal and Perinatal Death Review forms are filled in - 128 maternal
reviews since 2023, 564 perinatal - but their coded cause field is empty in
every single record.

The causes are in the Medical Certificate of Cause of Death, HMIS 100, entered
as an anonymous DHIS2 event program. Jinja has 1,898 of them, and 1,343 of the
1,500 since January 2024 carry an underlying cause written as an ICD-11 term:
"BIRTH ASPHYXIA, UNSPECIFIED", "ESSENTIAL HYPERTENSION, UNSPECIFIED", and so
on. That is the only complete cause-of-death series this hospital has.

MATERNAL DEATHS COME FROM THE SAME PLACE

The certificate asks whether the deceased was pregnant and whether the
pregnancy contributed to the death. Where that answer is yes, the underlying
cause on the same certificate IS the maternal cause of death, coded, which is
what the review form was supposed to capture and does not. Twenty-four such
records exist since January 2024 - anaemia, hypovolaemic shock, pre-eclampsia,
antepartum haemorrhage. It is a thin series and it is labelled as one.

PRIVACY

A certificate names the deceased. This module reads events in order to count
them and keeps only two fields from each: the underlying cause and the
pregnancy-contribution flag. Nothing else is copied out of the response, no
event is returned to the browser, and no identifier is logged. What leaves this
module is a tally.
"""
import re
from datetime import date, timedelta

from . import analytics, periods

# HMIS 100 - Medical Certificate of Cause of Death, an event program without
# registration. Resolved by name at runtime rather than pinned, because a UID
# is exactly the sort of thing that differs between instances.
MCCOD_PROGRAM_NAME = "Medical Certificate of Cause of Death"

# The three fields this module reads, and nothing else.
UNDERLYING_CAUSE = "QTKk2Xt8KDu"   # "State the underlying cause_FINAL_on the lowest used line"
PREGNANCY_CONTRIBUTED = "AJAraEcfH63"   # "Did the pregnancy contribute to the death?"
WAS_PREGNANT = "zcn7acUB6x1"       # "For women, was the deceased pregnant?"
STILLBORN = "ivnHp4M4hFF"          # "Stillborn?"

TOP_N = 5
MAX_EVENTS = 2000

# 033B's weekly attendance and death tallies, which give the denominator and a
# cross-check on the certificate count.
SURV_SEEN_CODE = "AP02"     # Total OPD
SURV_NEW_CODE = "AP01"      # OPD New
SURV_DEATHS_CODE = "AP03"   # Total Deaths


def _programs(session=None) -> list:
    s = analytics._session(session)
    r = s.get(f"{analytics._base()}/api/programs.json",
              params={"fields": "id,name", "paging": "false"}, timeout=30)
    r.raise_for_status()
    return r.json().get("programs") or []


def mccod_program_id(session=None) -> str:
    def produce():
        for p in _programs(session=session):
            if MCCOD_PROGRAM_NAME.lower() in str(p.get("name", "")).lower():
                return p["id"]
        raise RuntimeError(
            "The Medical Certificate of Cause of Death program was not found on "
            f"{analytics._base()}. Causes of death are recorded there rather than in "
            "any aggregate data set, so without it this chart has no causes to show.")
    return analytics._cached("mccod_program", produce)


# Abbreviations that must survive sentence-casing. An earlier version kept any
# short all-capital word, which is a rule that cannot tell APH from "DUE" and
# produced "Pneumonitis DUE TO inhalation OF FOOD OR vomit". A list is longer
# but it is right, and it is the sort of thing a clinician can correct.
ABBREVIATIONS = {
    "HIV", "AIDS", "TB", "MTB", "APH", "PPH", "COPD", "RTA", "RTI", "ARDS",
    "CKD", "AKI", "DM", "HTN", "IUGR", "PROM", "PPROM", "DIC", "SGA", "LGA",
    "ICU", "CNS", "GI", "UTI", "STI", "PID", "SARI", "AFP", "VHF", "NEC",
}


def tidy_cause(raw: str) -> str:
    """An ICD-11 term as a person would say it.

    The certificate stores the full term, which is written for a coder rather
    than for a chart axis: "ESSENTIAL HYPERTENSION, UNSPECIFIED" becomes
    "Essential hypertension". Only the trailing qualifier is dropped - the term
    itself is never reworded, because two conditions that differ by one word
    are two conditions."""
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return ""
    text = re.sub(r",?\s*(UNSPECIFIED|NOT ELSEWHERE CLASSIFIED|NOS)\.?$", "", text, flags=re.I)
    text = text.strip(" ,.;")
    if not text:
        return ""
    out = []
    for i, word in enumerate(text.split(" ")):
        bare = word.strip("(),.;:")
        if bare.upper() in ABBREVIATIONS or any(ch.isdigit() for ch in bare):
            out.append(word.upper() if bare.upper() in ABBREVIATIONS else word)
        elif i == 0:
            out.append(word.capitalize())
        else:
            out.append(word.lower())
    return " ".join(out)


def _events(start: date, end: date, org_unit: str, session=None) -> list:
    """MCCOD events in the window, reduced to the two fields this module uses.

    The reduction happens here, on the first line that touches the response, so
    that no part of a certificate travels any further than it has to."""
    s = analytics._session(session)
    r = s.get(f"{analytics._base()}/api/tracker/events", params={
        "program": mccod_program_id(session=session),
        "orgUnit": org_unit,
        "ouMode": "SELECTED",
        "occurredAfter": start.isoformat(),
        "occurredBefore": end.isoformat(),
        "pageSize": str(MAX_EVENTS),
        "fields": "dataValues[dataElement,value]",
    }, timeout=90)
    if r.status_code in (401, 403):
        raise RuntimeError(
            "DHIS2 refused the death certificates for this hospital "
            f"({r.status_code}). The account can read aggregate data but needs access to "
            "the HMIS 100 program to count causes of death.")
    r.raise_for_status()
    payload = r.json()
    raw = payload.get("instances") or payload.get("events") or []

    kept = []
    for ev in raw:
        picked = {}
        for dv in ev.get("dataValues") or []:
            de = dv.get("dataElement")
            if de in (UNDERLYING_CAUSE, PREGNANCY_CONTRIBUTED, WAS_PREGNANT, STILLBORN):
                picked[de] = dv.get("value")
        kept.append(picked)
    return kept


def _is_yes(value) -> bool:
    return str(value or "").strip().lower() in ("yes", "true", "1")


def _top(counts: dict, n: int = TOP_N) -> list:
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"cause": c, "deaths": v} for c, v in ordered[:n]]


def _denominator(period: str, org_unit: str, session=None) -> dict:
    """Patients seen in the period, from whichever return covers that cadence.

    Weekly comes from 033B's own attendance tally; monthly from 105:01's new
    and re-attendances. Both are attendances rather than people: a patient seen
    twice in the week is two attendances, which is what the Ministry's own
    denominators do."""
    from .metadata import mapping
    m = mapping()
    week = periods.parse_week_period(period)
    if week:
        idx = {str(k).upper(): v for k, v in (m.get("HMIS033B_codeIndex") or {}).items()}
        dx = [idx.get(SURV_NEW_CODE.upper()), idx.get(SURV_SEEN_CODE.upper()),
              idx.get(SURV_DEATHS_CODE.upper())]
        res = analytics.query([d for d in dx if d], org_unit, period, session=session)
        got = {}
        for row in res["rows"]:
            got[row.get("dx")] = analytics._num(row.get("value"))
        seen = got.get(idx.get(SURV_SEEN_CODE.upper()))
        if seen is None:
            seen = got.get(idx.get(SURV_NEW_CODE.upper()))
        return {"seen": seen, "reportedDeaths": got.get(idx.get(SURV_DEATHS_CODE.upper())),
                "source": "033B attendance (AP02)"}

    key = m["keyDataElements"]
    res = analytics.query([key["OA01_newAttendance"], key["OA02_reAttendance"]],
                          org_unit, period, session=session)
    total = 0
    seen_any = False
    for row in res["rows"]:
        v = analytics._num(row.get("value"))
        if v is not None:
            total += v
            seen_any = True
    return {"seen": total if seen_any else None, "reportedDeaths": None,
            "source": "105:01 attendance (OA01 + OA02)"}


# How far back the bars reach. Year to date is the default because a rolling
# quarter is too thin here: Jinja certified 101 causes in the whole of 2026 to
# date, so thirteen weeks of them is a top five of threes and twos, and a bar
# chart of threes and twos invites a reader to rank noise.
WINDOWS = {
    "ytd": "Since 1 January",
    "13w": "Last 13 weeks",
    "12m": "Last 12 months",
    "24m": "Last 24 months",
}
DEFAULT_WINDOW = "ytd"


def _window_start(window: str, end: date) -> date:
    if window == "13w":
        return end - timedelta(weeks=13)
    if window == "12m":
        return date(end.year - 1, end.month, 1)
    if window == "24m":
        return date(end.year - 2, end.month, 1)
    return date(end.year, 1, 1)


def summary(period: str, window: str = DEFAULT_WINDOW, scope: str = "facility",
            session=None) -> dict:
    """Deaths and their causes for one period, with the rate they imply.

    Two windows, deliberately. The RATE is for the period asked about, because
    that is the question - how many of the people seen this week died. The
    CAUSES are counted over a longer window ending with it, because Jinja
    certifies about four deaths a week and a top five drawn from four deaths is
    five bars of one.
    """
    h = analytics.hierarchy(session=session)
    if scope not in analytics.SCOPES:
        raise RuntimeError(f"Unknown scope '{scope}'. Use one of: "
                           + ", ".join(analytics.SCOPES))
    ou = h[scope]

    bounds = periods.bounds("Weekly", period) or periods.bounds("Monthly", period)
    if not bounds:
        raise RuntimeError(
            f"'{period}' is not a period this chart understands. Give an ISO week "
            "(2026W35) or a month (202608).")
    start, end = bounds

    window = (window or DEFAULT_WINDOW).lower()
    if window not in WINDOWS:
        raise RuntimeError(f"Unknown window '{window}'. Use one of: "
                           + ", ".join(WINDOWS))
    window_start = _window_start(window, end)
    events = _events(window_start, end + timedelta(days=1), ou["id"], session=session)

    all_cause, mpdsr = {}, {}
    certified = maternal_n = perinatal_n = 0
    for ev in events:
        cause = tidy_cause(ev.get(UNDERLYING_CAUSE))
        if not cause:
            continue
        certified += 1
        all_cause[cause] = all_cause.get(cause, 0) + 1
        # MPDSR is maternal AND perinatal, so both halves are counted: a death
        # the pregnancy contributed to, and a stillbirth. Reading only the
        # first would put a heading over a chart that answered half of it.
        is_maternal = _is_yes(ev.get(PREGNANCY_CONTRIBUTED))
        is_perinatal = _is_yes(ev.get(STILLBORN))
        if is_maternal:
            maternal_n += 1
        if is_perinatal:
            perinatal_n += 1
        if is_maternal or is_perinatal:
            mpdsr[cause] = mpdsr.get(cause, 0) + 1

    denom = _denominator(period, ou["id"], session=session)
    seen = denom.get("seen")
    period_deaths = denom.get("reportedDeaths")
    rate = None
    if seen and period_deaths is not None and seen > 0:
        rate = round((period_deaths / seen) * 1000, 2)

    return {
        "orgUnit": {"id": ou["id"], "name": ou["name"]},
        "scope": scope,
        "period": period,
        "periodLabel": periods.describe("Weekly" if periods.parse_week_period(period)
                                        else "Monthly", period),
        "window": {"key": window, "label": WINDOWS[window],
                   "from": window_start.isoformat(), "to": end.isoformat(),
                   "days": (end - window_start).days},
        "windows": [{"key": k, "label": v} for k, v in WINDOWS.items()],
        "seen": seen,
        "deaths": period_deaths,
        # Per thousand attendances, which is how a facility death rate is read.
        # Per cent would put every honest figure at 0.1 and round most to zero.
        "ratePerThousand": rate,
        "denominatorSource": denom.get("source"),
        "allCause": _top(all_cause),
        "mpdsr": _top(mpdsr),
        "certifiedInWindow": certified,
        "mpdsrInWindow": sum(mpdsr.values()),
        # The split, because "MPDSR" over one bar chart says nothing about
        # which half the bars came from, and at this hospital it is mostly the
        # perinatal half.
        "maternalInWindow": maternal_n,
        "perinatalInWindow": perinatal_n,
        # Said plainly: these bars are a count of certificates, and a hospital
        # that certifies half its deaths shows half its causes.
        "eventsRead": len(events),
    }
