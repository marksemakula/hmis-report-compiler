"""DHIS2 period identifiers.

The eight Uganda HMIS data sets this compiler handles run on three cadences,
each with its own identifier format:

    Monthly    YYYYMM    202606
    Weekly     YYYYWn    2026W35     ISO-8601, Monday-start, week 1 contains 4 Jan
    Quarterly  YYYYQn    2026Q3      Q1 = Jan-Mar

Weekly is the awkward one. SQL Server's DATEPART(week, ...) is not ISO and will
disagree with DHIS2 by a day or a whole week depending on the year; the ISO
calendar is used throughout here and DATEPART(ISO_WEEK, ...) in the extraction
scripts.
"""
import re
from datetime import date, timedelta

MONTH_RE   = re.compile(r"^(\d{4})(\d{2})$")
WEEK_RE    = re.compile(r"^(\d{4})W(\d{1,2})$", re.IGNORECASE)
QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$", re.IGNORECASE)

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

FORMAT_HINT = {
    "Monthly":   "YYYYMM, for example 202606",
    "Weekly":    "YYYYWnn, for example 2026W35",
    "Quarterly": "YYYYQn, for example 2026Q3",
}


# ---------------------------------------------------------------- weekly
def week_period(d: date) -> str:
    """DHIS2 weekly period identifier for the week containing `d`."""
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}W{iso_week}"


def parse_week_period(period: str):
    """('2026W35') -> (2026, 35), or None when the identifier is malformed."""
    m = WEEK_RE.match(str(period).strip())
    if not m:
        return None
    year, week = int(m.group(1)), int(m.group(2))
    if not (1 <= week <= 53):
        return None
    # Reject week 53 in years that only have 52 ISO weeks.
    if week == 53 and date(year, 12, 28).isocalendar()[1] != 53:
        return None
    return year, week


def week_bounds(period: str):
    """(Monday, Sunday) dates covered by a DHIS2 weekly period."""
    parsed = parse_week_period(period)
    if not parsed:
        return None
    year, week = parsed
    monday = date.fromisocalendar(year, week, 1)
    return monday, monday + timedelta(days=6)


def describe_week(period: str) -> str:
    b = week_bounds(period)
    if not b:
        return period
    start, end = b
    return f"{period} ({start.strftime('%d %b')} - {end.strftime('%d %b %Y')})"


# ---------------------------------------------------------------- monthly
def parse_month_period(period: str):
    m = MONTH_RE.match(str(period).strip())
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12):
        return None
    return year, month


def month_bounds(period: str):
    parsed = parse_month_period(period)
    if not parsed:
        return None
    year, month = parsed
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return start, end


# ---------------------------------------------------------------- quarterly
def parse_quarter_period(period: str):
    m = QUARTER_RE.match(str(period).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def quarter_bounds(period: str):
    parsed = parse_quarter_period(period)
    if not parsed:
        return None
    year, q = parsed
    start_month = 3 * (q - 1) + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    end = date(year + (end_month == 12), (end_month % 12) + 1, 1) - timedelta(days=1)
    return start, end


# ---------------------------------------------------------------- generic
def parse(period_type: str, period: str):
    """Return the parsed period, or None when it does not fit the cadence."""
    pt = (period_type or "").capitalize()
    period = str(period or "").strip().upper()
    if pt == "Monthly":
        return parse_month_period(period)
    if pt == "Weekly":
        return parse_week_period(period)
    if pt == "Quarterly":
        return parse_quarter_period(period)
    return None


def bounds(period_type: str, period: str):
    pt = (period_type or "").capitalize()
    period = str(period or "").strip().upper()
    if pt == "Monthly":
        return month_bounds(period)
    if pt == "Weekly":
        return week_bounds(period)
    if pt == "Quarterly":
        return quarter_bounds(period)
    return None


def describe(period_type: str, period: str) -> str:
    """A period identifier a person can read without decoding it."""
    pt = (period_type or "").capitalize()
    period = str(period or "").strip().upper()
    parsed = parse(pt, period)
    if not parsed:
        return period
    if pt == "Monthly":
        year, month = parsed
        return f"{MONTHS[month - 1]} {year}"
    if pt == "Weekly":
        return describe_week(period)
    if pt == "Quarterly":
        year, q = parsed
        first = MONTHS[3 * (q - 1)]
        last = MONTHS[3 * (q - 1) + 2]
        return f"Q{q} {year} ({first}-{last})"
    return period


def default_period(period_type: str, today: date = None) -> str:
    """The period a user most likely wants: the last one that has closed."""
    today = today or date.today()
    pt = (period_type or "").capitalize()
    if pt == "Weekly":
        return week_period(today - timedelta(days=7))
    if pt == "Quarterly":
        q = (today.month - 1) // 3 + 1
        year = today.year
        q -= 1
        if q == 0:
            q, year = 4, year - 1
        return f"{year}Q{q}"
    first_of_month = date(today.year, today.month, 1)
    prev = first_of_month - timedelta(days=1)
    return f"{prev.year}{prev.month:02d}"
