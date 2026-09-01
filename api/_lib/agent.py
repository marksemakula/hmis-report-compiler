"""On-premise extraction agent — job queue and result ingestion.

ClinicMaster sits at 172.20.0.230, a private address on the hospital LAN. A
Vercel function cannot route to it, so the compiler does not reach into the
database. Instead a small agent runs *inside* the hospital and reaches out:

    ClinicMaster 172.20.0.230          Vercel
             ^                            ^
             | read-only T-SQL            | HTTPS, outbound only
             |                            |
          jrrh-agent  ────────────────────┘
          polls for jobs, aggregates on site, posts counts

Three properties follow, and they are the reason for this design rather than a
tunnel:

  * No inbound firewall rule. The agent only makes outbound HTTPS calls.
  * No database credential ever reaches Vercel.
  * No patient-level data leaves the hospital. The agent posts *strata* —
    counts by diagnosis, age band, sex and visit type — never rows. A stratum
    with a count of one still names no one, and the ingestion below rejects
    any payload carrying a field that could identify a patient.

The server also never sends SQL to the agent. A job says only "105:01 for
June 2026"; the queries live in the agent's own package, versioned in this
repo. A compromised server therefore cannot make the agent run arbitrary
statements against a database full of HIV records.
"""
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone

from .metadata import mapping


def _http_error(status: int, detail: str):
    """Raise FastAPI's HTTPException when running under the API, and a plain
    error carrying the same status when not.

    The import is deferred so that validation and aggregation in this module can
    be exercised by scripts/test_agent.py on a machine with nothing installed —
    which is the whole point of those checks being runnable before a push."""
    try:
        from fastapi import HTTPException
        return HTTPException(status_code=status, detail=detail)
    except ImportError:  # pragma: no cover - only outside the API runtime
        exc = RuntimeError(detail)
        exc.status_code = status
        return exc

# Bounds on what an agent may post. Generous for a busy regional referral
# hospital, tight enough that a runaway or hostile agent cannot fill the table.
MAX_STRATA = 20000
MAX_COUNT = 10_000_000

STRATUM_KEYS = {"diagnosis", "band", "sex", "visit", "n"}

# Extracts carry two grains in one file. A row whose diagnosis is this sentinel
# counts VISITS (one per visit, for OA01/OA02); every other row counts
# DIAGNOSES, of which a single visit may contribute several. Keeping them in one
# file keeps the upload a single artefact; keeping them distinguishable keeps
# attendance from being multiplied by the number of conditions recorded.
ATTENDANCE_SENTINEL = "(attendance)"

# Fields that must never appear in a payload. Their presence means the agent
# is sending patient-level data, which is a defect in the agent rather than
# something to quietly accept and store.
FORBIDDEN_KEYS = {
    "patientno", "patient_no", "patientid", "patient_id", "name", "firstname",
    "lastname", "middlename", "clinicno", "clinic_no", "artno", "art_no",
    "nationalid", "nationalidno", "phone", "address", "dob", "birthdate",
    "birth_date", "visitno", "visit_no", "specimenno", "specimen_no", "nin",
}

SEXES = {"male": "Male", "m": "Male", "female": "Female", "f": "Female"}
VISITS = {"new": "New", "re": "Re", "re-attendance": "Re", "reattendance": "Re"}

JOB_STATES = ("QUEUED", "RUNNING", "DONE", "FAILED", "EXPIRED")


# ---------------------------------------------------------------- auth
def agent_key() -> str:
    key = os.environ.get("AGENT_KEY", "")
    if not key or len(key) < 24:
        raise _http_error(503,
            "The extraction agent is not configured. Set AGENT_KEY (at least "
            "24 random characters) in the project settings and give the same "
            "value to the on-premise agent.")
    return key


def require_agent(authorization: str = ""):
    """Constant-time bearer check. Agents are machines, not users: they carry a
    shared key rather than a session, and may not touch any user-facing route."""
    expected = agent_key()
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token or not hmac.compare_digest(token, expected):
        raise _http_error(401, "Invalid agent credentials")
    return True


def fingerprint(key: str) -> str:
    """A short, non-reversible label so logs and the UI can distinguish agents
    without ever recording the key itself."""
    return hashlib.sha256(key.encode()).hexdigest()[:12]


# ---------------------------------------------------------------- schema
def ensure_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS extraction_jobs (
        id            SERIAL PRIMARY KEY,
        report_type   VARCHAR(16)  NOT NULL,
        period        VARCHAR(16)  NOT NULL,
        state         VARCHAR(16)  NOT NULL DEFAULT 'QUEUED',
        requested_by  VARCHAR(255) NOT NULL,
        requested_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
        claimed_at    TIMESTAMPTZ,
        finished_at   TIMESTAMPTZ,
        agent         VARCHAR(32),
        strata        JSONB,
        stratum_count INTEGER,
        message       TEXT,
        import_id     INTEGER)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS agent_heartbeats (
        agent      VARCHAR(32) PRIMARY KEY,
        last_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
        version    VARCHAR(32),
        host       VARCHAR(128),
        note       TEXT)""")


# ---------------------------------------------------------------- validation
def _clean_int(value, field):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a whole number, got {value!r}")
    if n < 0:
        raise ValueError(f"{field} must not be negative, got {n}")
    if n > MAX_COUNT:
        raise ValueError(f"{field} of {n} exceeds the permitted maximum")
    return n


def validate_strata(payload) -> list:
    """Accept only anonymous aggregate strata. Returns the cleaned list.

    Raises ValueError with a message the agent's author can act on — these are
    developer errors, not user errors, and vagueness helps nobody."""
    if not isinstance(payload, list):
        raise ValueError("strata must be a list")
    if len(payload) > MAX_STRATA:
        raise ValueError(f"{len(payload)} strata exceeds the maximum of {MAX_STRATA}")

    bands = set(mapping()["categoryCombos"]["OPD_AGE_SEX"]["cocs"])
    valid_bands = {b.split(",")[0].strip() for b in bands}

    out = []
    for i, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"stratum {i} is not an object")

        lowered = {str(k).lower().replace(" ", "") for k in row}
        leaked = lowered & FORBIDDEN_KEYS
        if leaked:
            raise ValueError(
                f"stratum {i} carries patient-identifying field(s) {sorted(leaked)}. "
                "The agent must aggregate on site and post counts only; no "
                "patient-level data may leave the hospital network.")

        unknown = set(row) - STRATUM_KEYS
        if unknown:
            raise ValueError(f"stratum {i} has unexpected field(s) {sorted(unknown)}")

        diagnosis = str(row.get("diagnosis") or "").strip()
        if not diagnosis:
            raise ValueError(f"stratum {i} has no diagnosis")
        if len(diagnosis) > 300:
            raise ValueError(f"stratum {i} diagnosis is implausibly long")

        band = str(row.get("band") or "").strip()
        if band not in valid_bands:
            raise ValueError(
                f"stratum {i} has age band {band!r}; expected one of {sorted(valid_bands)}")

        sex = SEXES.get(str(row.get("sex") or "").strip().lower())
        if not sex:
            raise ValueError(f"stratum {i} has unrecognised sex {row.get('sex')!r}")

        visit = VISITS.get(str(row.get("visit") or "").strip().lower())
        if not visit:
            raise ValueError(
                f"stratum {i} has unrecognised visit type {row.get('visit')!r}; "
                "expected New or Re-attendance")

        n = _clean_int(row.get("n"), f"stratum {i} count")
        if n == 0:
            continue  # an empty stratum carries nothing

        out.append({"diagnosis": diagnosis, "band": band, "sex": sex,
                    "visit": visit, "n": n})
    return out


def summarise(strata: list) -> dict:
    """Totals for the audit trail and the UI.

    Visits and diagnoses are counted from their own rows. Summing every n would
    double-count, because an extract carries both grains: one attendance row per
    visit plus one row per condition recorded at it."""
    att = [s for s in strata if s["diagnosis"] == ATTENDANCE_SENTINEL]
    cond = [s for s in strata if s["diagnosis"] != ATTENDANCE_SENTINEL]
    return {
        "strata": len(strata),
        "visits": sum(s["n"] for s in att),
        "new": sum(s["n"] for s in att if s["visit"] == "New"),
        "re": sum(s["n"] for s in att if s["visit"] == "Re"),
        "conditions": sum(s["n"] for s in cond),
        "diagnoses": len({s["diagnosis"] for s in cond}),
    }


# ---------------------------------------------------------------- job queue
def queue_job(cur, report_type: str, period: str, requested_by: str) -> int:
    ensure_tables(cur)
    # One live job per report and period; re-requesting supersedes rather than
    # queueing a second identical extraction.
    cur.execute(
        """UPDATE extraction_jobs SET state='EXPIRED', message='Superseded by a newer request'
           WHERE report_type=%s AND period=%s AND state IN ('QUEUED','RUNNING')""",
        (report_type, period))
    cur.execute(
        """INSERT INTO extraction_jobs (report_type, period, requested_by)
           VALUES (%s,%s,%s) RETURNING id""",
        (report_type, period, requested_by))
    return cur.fetchone()["id"]


def claim_job(cur, agent_id: str):
    """Hand the oldest queued job to a polling agent, atomically."""
    ensure_tables(cur)
    cur.execute(
        """UPDATE extraction_jobs SET state='RUNNING', claimed_at=now(), agent=%s
           WHERE id = (SELECT id FROM extraction_jobs WHERE state='QUEUED'
                       ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
           RETURNING id, report_type, period""",
        (agent_id,))
    return cur.fetchone()


def record_heartbeat(cur, agent_id: str, version: str = "", host: str = "", note: str = ""):
    ensure_tables(cur)
    cur.execute(
        """INSERT INTO agent_heartbeats (agent, version, host, note)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT (agent) DO UPDATE
           SET last_seen=now(), version=EXCLUDED.version,
               host=EXCLUDED.host, note=EXCLUDED.note""",
        (agent_id, version[:32], host[:128], note[:500]))


def agent_status(cur) -> dict:
    ensure_tables(cur)
    cur.execute("""SELECT agent, last_seen, version, host,
                          EXTRACT(EPOCH FROM (now() - last_seen)) AS seconds_ago
                   FROM agent_heartbeats ORDER BY last_seen DESC LIMIT 5""")
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["last_seen"] = str(r["last_seen"])
        r["seconds_ago"] = int(r["seconds_ago"] or 0)
        r["online"] = r["seconds_ago"] < 180
    return {"agents": rows, "online": any(r["online"] for r in rows)}


def strata_to_rows(strata: list) -> list:
    """Expand validated strata into the row shape the existing OPD compiler
    consumes, so the connector and the upload path go through identical
    aggregation and cannot drift apart.

    One row per stratum carrying its count, rather than n duplicated rows: the
    compiler is adjusted to honour a weight, which keeps a 40,000-visit month
    to a few hundred rows instead of forty thousand."""
    rows = []
    for s in strata:
        is_attendance = s["diagnosis"] == ATTENDANCE_SENTINEL
        rows.append({
            # An attendance row carries no condition, so it must not also be
            # tallied against a data element.
            "diagnosis_code": "" if is_attendance else s["diagnosis"],
            "age_band": s["band"],
            "sex": s["sex"],
            "visit_type": s["visit"],
            "weight": s["n"],
            "count_attendance": is_attendance,
            "in_period": True,
        })
    return rows
