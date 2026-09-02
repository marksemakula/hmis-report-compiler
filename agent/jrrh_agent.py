#!/usr/bin/env python3
"""JRRH extraction agent - runs inside the hospital network.

ClinicMaster is at a private address the cloud application cannot reach. This
agent bridges that gap in the safe direction: it makes outbound HTTPS calls
only, so no firewall rule is opened and the database is never exposed.

What it does, on a loop:

    1. asks the compiler whether any extraction is waiting
    2. runs the matching read-only query against ClinicMaster
    3. aggregates on this machine into anonymous strata
    4. posts the counts back

What it never does: send patient-level data. A stratum is a count of visits by
diagnosis, age band, sex and visit type. No name, number, date of birth or visit
identifier leaves this network, and the server rejects any payload that carries
one.

Usage
-----
    python jrrh_agent.py --once      run any waiting job and stop
    python jrrh_agent.py             poll continuously
    python jrrh_agent.py --schema    print the ClinicMaster columns the
                                     diagnosis query still needs
    python jrrh_agent.py --check     test both connections and exit

Configuration, by environment variable or a .env file beside this script:

    COMPILER_URL   https://hmis-report-compiler.vercel.app
    AGENT_KEY      the same secret set in the compiler's settings
    CM_SERVER      172.20.0.230
    CM_DATABASE    ClinicMasterMOH
    CM_USER        a READ-ONLY SQL login
    CM_PASSWORD    its password
    POLL_SECONDS   default 20
"""
import argparse
import datetime as dt
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import queries  # noqa: E402

VERSION = "1.0.0"

# ---------------------------------------------------------------- age bands
# These must match api/_lib/compiler.py exactly. scripts/test_agent.py asserts
# they agree; if that test fails, the two have drifted and the figures from the
# connector will no longer match the upload path.
OPD_BANDS = [
    (28 / 365.0, "0-28Dys"),
    (5.0, "29Dys-4Yrs"),
    (10.0, "5-9Yrs"),
    (20.0, "10-19Yrs"),
    (999.0, "20+Yrs"),
]


def opd_band(age_years: float) -> str:
    for limit, label in OPD_BANDS:
        if age_years < limit or (label == "0-28Dys" and age_years <= limit):
            return label
    return "20+Yrs"


# ClinicMaster's visit categories, mapped to the two HMIS attendance rows.
# Anything not named here is treated as a first presentation, which matches the
# adapter the compiler already applies to raw EMR exports.
RE_ATTENDANCE = {
    "follow up", "rtt - return to treatment", "represented", "cddp",
}
SEXES = {"female": "Female", "f": "Female", "male": "Male", "m": "Male"}


def visit_type(category: str) -> str:
    return "Re" if str(category or "").strip().lower() in RE_ATTENDANCE else "New"


def normalise_sex(value):
    return SEXES.get(str(value or "").strip().lower())


# ---------------------------------------------------------------- config
def load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cfg(name, default=None, required=False):
    v = os.environ.get(name, default)
    if required and not v:
        sys.exit(f"Configuration error: {name} is not set. See the header of this file.")
    return v


# ---------------------------------------------------------------- database
def connect():
    """Open a read-only connection to ClinicMaster.

    pyodbc is preferred; pymssql is accepted so the agent can run on a machine
    without the Microsoft ODBC driver installed."""
    server = cfg("CM_SERVER", "172.20.0.230")
    database = cfg("CM_DATABASE", queries.DATABASE)
    user = cfg("CM_USER", required=True)
    password = cfg("CM_PASSWORD", required=True)

    try:
        import pyodbc
        for driver in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server",
                       "SQL Server"):
            try:
                conn = pyodbc.connect(
                    f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};"
                    f"UID={user};PWD={password};TrustServerCertificate=yes;"
                    "ApplicationIntent=ReadOnly;Connection Timeout=15",
                    timeout=15, readonly=True)
                return conn, "pyodbc/" + driver
            except Exception:
                continue
    except ImportError:
        pass

    try:
        import pymssql
        conn = pymssql.connect(server=server, user=user, password=password,
                               database=database, login_timeout=15, timeout=300)
        return conn, "pymssql"
    except ImportError:
        sys.exit("No SQL Server driver found. Install one:\n"
                 "  pip install pyodbc      (needs the Microsoft ODBC driver)\n"
                 "  pip install pymssql     (self-contained, usually easier)")
    except Exception as exc:
        sys.exit(f"Could not connect to ClinicMaster at {server}: {exc}")


def run_query(conn, sql, params=(), label="query"):
    queries.check_read_only(sql, label)
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


# ---------------------------------------------------------------- periods
def month_bounds(period: str):
    year, month = int(period[:4]), int(period[4:6])
    start = dt.date(year, month, 1)
    end = dt.date(year + (month == 12), (month % 12) + 1, 1)
    return start, end


# ---------------------------------------------------------------- extraction
def extract_opd(conn, period: str):
    """Return (strata, notes). Strata carry counts only."""
    start, end = month_bounds(period)
    notes = []

    if queries.DIAGNOSIS_SOURCE.get("confirmed"):
        sql = queries.opd_diagnosis_sql()
        rows = run_query(conn, sql, (start, end), "OPD diagnosis extract")
        keyed = "diagnosis"
    else:
        rows = run_query(conn, queries.OPD_ATTENDANCE, (start, end), "OPD attendance extract")
        keyed = None
        notes.append(
            "Diagnosis columns are not yet confirmed, so this run carries attendance "
            "only. Run --schema and complete DIAGNOSIS_SOURCE in queries.py.")

    tally, skipped = {}, {"no_age": 0, "no_sex": 0}
    for r in rows:
        n = int(r.get("n") or 0)
        if n <= 0:
            continue
        age = r.get("age_years")
        if age is None:
            skipped["no_age"] += n
            continue
        sex = normalise_sex(r.get("sex"))
        if not sex:
            skipped["no_sex"] += n
            continue
        band = opd_band(float(age))
        visit = visit_type(r.get("visit_category"))
        diagnosis = str(r.get(keyed) or "").strip() if keyed else "(attendance only)"
        if not diagnosis:
            diagnosis = "(no diagnosis recorded)"
        key = (diagnosis, band, sex, visit)
        tally[key] = tally.get(key, 0) + n

    if skipped["no_age"]:
        notes.append(f"{skipped['no_age']:,} visits had no usable date of birth and "
                     "could not be banded.")
    if skipped["no_sex"]:
        notes.append(f"{skipped['no_sex']:,} visits had no recognised sex.")

    strata = [{"diagnosis": d, "band": b, "sex": s, "visit": v, "n": n}
              for (d, b, s, v), n in sorted(tally.items())]
    return strata, notes


EXTRACTORS = {"OPD": extract_opd}


# ---------------------------------------------------------------- transport
def api(path, payload=None, method=None, timeout=120):
    url = cfg("COMPILER_URL", required=True).rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    req.add_header("Authorization", "Bearer " + cfg("AGENT_KEY", required=True))
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", f"jrrh-agent/{VERSION}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:800]
        raise RuntimeError(f"{method or 'GET'} {path} -> HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach the compiler at {url}: {e.reason}")


def heartbeat(note=""):
    try:
        api("/api/py/agent/heartbeat",
            {"version": VERSION, "host": socket.gethostname(), "note": note})
    except Exception as exc:
        print(f"  heartbeat failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------- main loop
def run_job(job):
    rt, period = job["report_type"], job["period"]
    print(f"  job {job['id']}: {rt} {period}")
    extractor = EXTRACTORS.get(rt)
    if not extractor:
        api(f"/api/py/agent/jobs/{job['id']}/result",
            {"error": f"This agent has no extractor for {rt}."})
        print(f"  no extractor for {rt} - reported back")
        return

    conn, driver = connect()
    try:
        started = time.time()
        strata, notes = extractor(conn, period)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    total = sum(s["n"] for s in strata)
    print(f"  {len(strata):,} strata, {total:,} visits, {time.time() - started:.1f}s via {driver}")
    for n in notes:
        print(f"  note: {n}")

    result = api(f"/api/py/agent/jobs/{job['id']}/result",
                 {"strata": strata, "notes": notes, "driver": driver})
    print(f"  posted - import {result.get('import_id')}")


def poll_once():
    job = api("/api/py/agent/next").get("job")
    if not job:
        return False
    try:
        run_job(job)
    except Exception as exc:
        print(f"  job failed: {exc}", file=sys.stderr)
        try:
            api(f"/api/py/agent/jobs/{job['id']}/result", {"error": str(exc)[:1500]})
        except Exception:
            pass
    return True


def main():
    load_env()
    ap = argparse.ArgumentParser(description="JRRH ClinicMaster extraction agent")
    ap.add_argument("--once", action="store_true", help="run any waiting job, then stop")
    ap.add_argument("--schema", action="store_true", help="print ClinicMaster columns and exit")
    ap.add_argument("--check", action="store_true", help="test both connections and exit")
    args = ap.parse_args()

    if args.schema:
        conn, driver = connect()
        print(f"Connected via {driver}\n")
        for row in run_query(conn, queries.SCHEMA_PROBE, (), "schema probe"):
            print(f"TABLE: {row['table_name']}\n  {row['columns']}\n")
        conn.close()
        return

    if args.check:
        conn, driver = connect()
        rows = run_query(conn, f"SELECT TOP 1 1 AS ok FROM {queries.DATABASE}.dbo.Visits", (), "check")
        conn.close()
        print(f"ClinicMaster: reachable via {driver} ({'ok' if rows else 'no rows'})")
        me = api("/api/py/agent/heartbeat", {"version": VERSION, "host": socket.gethostname(),
                                             "note": "check"})
        print(f"Compiler:     reachable, agent id {me.get('agent')}")
        print(f"Diagnosis columns confirmed: {queries.DIAGNOSIS_SOURCE.get('confirmed')}")
        return

    interval = int(cfg("POLL_SECONDS", "20"))
    print(f"jrrh-agent {VERSION} - polling {cfg('COMPILER_URL')} every {interval}s")
    heartbeat("started")
    if args.once:
        if not poll_once():
            print("  nothing waiting")
        return
    idle = 0
    while True:
        try:
            if poll_once():
                idle = 0
            else:
                idle += 1
                if idle % 15 == 0:
                    heartbeat("idle")
        except Exception as exc:
            print(f"  poll failed: {exc}", file=sys.stderr)
        time.sleep(interval)


if __name__ == "__main__":
    main()
