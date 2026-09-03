"""HMIS Report Compiler - FastAPI backend (deployed as a Vercel Python function)."""
import json
import os
import re
import sys

sys.path.append(os.path.dirname(__file__))

import requests

from fastapi import FastAPI, Header, HTTPException, Request, Response, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from _lib import db
from _lib.auth import issue_token, current_user, require_role
from _lib.validators import (
    IPD_COLUMNS, OPD_COLUMNS, mapping, parse_file, shape_mismatch, validate_rows,
)
from _lib.compiler import compile_opd, compile_ipd, compile_opd_strata
from _lib import agent as agentlib
from _lib.surveillance import (
    SURV_COLUMNS, check_consistency, compile_033b, describe_week,
    parse_week_period, template_csv, validate_surveillance_rows,
)
from _lib import consistency, coverage, dhis2, extract_scripts, forms, periods

EXPECTED_COLUMNS = {"OPD": OPD_COLUMNS, "IPD": IPD_COLUMNS, "SURV": SURV_COLUMNS}


def report_type_entry(report_type: str) -> dict:
    entry = mapping().get("reportTypes", {}).get((report_type or "").upper())
    if not entry:
        known = ", ".join(sorted(mapping().get("reportTypes", {})))
        err(f"Unknown report '{report_type}'. Known reports: {known}", 404)
    return entry


def check_period(report_type: str, period: str) -> str:
    """Each report carries its own cadence, so the identifier format follows it."""
    entry = report_type_entry(report_type)
    pt = entry["periodType"]
    period = (period or "").strip().upper()
    if not periods.parse(pt, period):
        err(f"{entry['short']} is a {pt.lower()} report, so period must be "
            f"in {periods.FORMAT_HINT.get(pt, pt)}")
    return period

app = FastAPI(title="HMIS Report Compiler", docs_url=None, redoc_url=None)


def err(detail, code=400):
    raise HTTPException(status_code=code, detail=detail)


@app.exception_handler(RuntimeError)
def _runtime_error(request: Request, exc: RuntimeError):
    """Surface an authored RuntimeError instead of an anonymous 500.

    The library raises RuntimeError for problems an operator can actually fix -
    DHIS2 credentials absent, metadata cache stale, a data set with no custom
    form - and each message says what to do. Without this handler every one of
    them reached the browser as "Internal Server Error", which is the least
    useful thing the app could possibly say about a fixable problem."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(Exception)
def _unhandled(request: Request, exc: Exception):
    """Anything genuinely unexpected. The message is NOT echoed - an arbitrary
    exception can carry a connection string or a token - but the type and the
    route are, which is enough to find it in the deployment logs."""
    return JSONResponse(status_code=500, content={
        "detail": f"Unexpected {type(exc).__name__} handling {request.url.path}. "
                  "The details are in the deployment logs; nothing was saved."})


# ---------------- auth ----------------

class LoginBody(BaseModel):
    email: str
    password: str


@app.post("/api/py/auth/login")
def login(body: LoginBody, response: Response):
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE lower(email)=lower(%s)", (body.email.strip(),))
            user = cur.fetchone()
    if not user or not db.verify_password(body.password, user["password_hash"]):
        err("The email address or password is incorrect", 401)
    token = issue_token(user)
    response.set_cookie("hmis_token", token, httponly=True, secure=True, samesite="lax", max_age=43200, path="/")
    db.audit(user["email"], "Signed in", {})
    return {"email": user["email"], "role": user["role"], "name": user["full_name"]}


@app.post("/api/py/auth/logout")
def logout(response: Response):
    response.delete_cookie("hmis_token", path="/")
    return {"ok": True}


@app.get("/api/py/auth/me")
def me(user: dict = Depends(current_user)):
    return {"email": user["sub"], "role": user["role"], "name": user.get("name", "")}


# ---------------- uploads ----------------

class UploadBody(BaseModel):
    blob_url: str
    filename: str
    report_type: str
    period: str


# Only a Vercel Blob URL may be fetched here. Without this the endpoint would
# take any URL a caller supplied and retrieve it with our storage credential
# attached, which is a request-forgery hole rather than a validation nicety.
#
# There were two definitions of this, one of them dead. The first wrote \\. in
# a raw string, which matches a literal backslash and so matched no real URL at
# all; it was harmless only because the second immediately replaced it. Deleting
# the "duplicate" second line, which is the obvious tidy-up, would have silently
# rejected every upload.
BLOB_URL_RE = re.compile(r"^https://[a-z0-9]+\.(private|public)\.blob\.vercel-storage\.com/")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@app.post("/api/py/upload")
def upload(body: UploadBody, user: dict = Depends(current_user)):
    """Ingest a register extract previously uploaded to Vercel Blob.

    The browser uploads the file directly to the private Blob store (client
    upload), then posts the blob URL here. This bypasses the hard 4.5 MB
    request-body limit on Vercel serverless functions.
    """
    require_role(user, "data_officer")
    entry = report_type_entry(body.report_type)
    if not entry.get("compiler"):
        err(f"{entry['short']} can be previewed but not yet compiled - no compiler "
            f"has been written for it. Reports that can be compiled today: "
            + ", ".join(sorted(k for k, v in mapping()["reportTypes"].items() if v.get("compiler"))))
    period = check_period(body.report_type, body.period)
    if not BLOB_URL_RE.match(body.blob_url):
        err("Invalid file reference")
    blob_token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not blob_token:
        err("File storage is not configured (BLOB_READ_WRITE_TOKEN is missing)", 500)
    try:
        resp = requests.get(
            body.blob_url,
            headers={"Authorization": f"Bearer {blob_token}"},
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        err(f"Could not fetch the uploaded file from storage: {exc}", 502)
    content = resp.content
    if len(content) > MAX_UPLOAD_BYTES:
        err("The file exceeds the 25 MB limit")
    expected = EXPECTED_COLUMNS[body.report_type]
    try:
        rows = parse_file(body.filename, content, expected_columns=expected)
    except Exception as exc:
        err(f"The file could not be parsed: {exc}")
    if not rows:
        err("The file contains no data rows. Check that the register was "
            "exported into a sheet whose first row has the template headers.")
    # Is this the right file for the report that was selected? Asking before
    # validation turns seventeen identical required-field lines about columns
    # the file was never going to have into one sentence naming what it is.
    mismatch = shape_mismatch(body.report_type, rows)
    if mismatch:
        err(mismatch)
    # A file written by a generated extraction script is already aggregated:
    # counts by diagnosis, age band, sex and visit type. Recognised by its
    # columns rather than its name, so a renamed file still works.
    source = "UPLOAD"
    context, surv_findings = {}, []
    # Every branch below can raise RuntimeError, and those messages are written
    # FOR the person reading them: "the 033B element list is empty, set
    # DHIS2_USERNAME and run Refresh metadata". Uncaught, FastAPI turned each of
    # them into a bare 500 Internal Server Error and the instruction was lost.
    # A configuration problem the operator can fix must never present as a crash.
    try:
        if body.report_type == "SURV":
            clean, errors, context = validate_surveillance_rows(rows, period)
            # Arithmetic the form implies but cannot enforce. Surfaced at
            # upload, while the figures can still be questioned, rather than
            # after they have been submitted to the national instance.
            surv_findings = check_consistency(clean, context)
        elif extract_scripts.looks_like_strata(rows[0].keys() if rows else None):
            try:
                strata = agentlib.validate_strata([
                    {k: v for k, v in r.items() if k in extract_scripts.strata_columns()}
                    for r in rows])
            except ValueError as exc:
                err(f"This looks like an extraction-script file, but it was rejected: {exc}")
            clean = agentlib.strata_to_rows(strata)
            errors = []
            source = "SCRIPT"
        else:
            clean, errors = validate_rows(body.report_type, rows, period)
    except HTTPException:
        raise                       # err() above; already has its own message
    except RuntimeError as exc:
        err(str(exc), 503)
    in_period = sum(1 for r in clean if r["in_period"])

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE imported_data ADD COLUMN IF NOT EXISTS "
                        "source VARCHAR(32) NOT NULL DEFAULT 'UPLOAD'")
            cur.execute(
                """INSERT INTO imported_data
                   (file_name, report_type, period, row_count, error_count, original_data, validation_errors, uploaded_by, processing_status, source)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (body.filename, body.report_type, period, len(rows), len(errors),
                 json.dumps(clean), json.dumps(errors), user["sub"], "PENDING", source),
            )
            import_id = cur.fetchone()["id"]
    db.audit(user["sub"], "File uploaded", {
        "import_id": import_id, "file": body.filename, "type": body.report_type,
        "period": period, "rows": len(rows), "errors": len(errors),
    })
    return {
        "import_id": import_id,
        "rows": len(rows),
        "valid_rows": len(clean),
        "rows_in_period": in_period,
        "errors": errors[:200],
        "error_count": len(errors),
        # Extract metadata (the period actually covered, tests ordered against
        # tests resulted) and the consistency findings drawn from it.
        "context": context,
        "consistency": surv_findings,
    }


# ---------------- compile ----------------

class CompileBody(BaseModel):
    import_id: int


@app.post("/api/py/compile")
def compile_report(body: CompileBody, user: dict = Depends(current_user)):
    require_role(user, "data_officer")
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM imported_data WHERE id=%s", (body.import_id,))
            imp = cur.fetchone()
    if not imp:
        err("Import not found", 404)
    rows = imp["original_data"]
    if isinstance(rows, str):
        rows = json.loads(rows)
    # Rows staged by the on-premise agent arrive pre-banded and weighted, so
    # they take the strata compiler. Both paths share the same code index,
    # category combos and unmapped-code reporting, and must agree.
    from_agent = str(imp.get("source") or "UPLOAD").upper() in ("AGENT", "SCRIPT")
    if imp["report_type"] == "OPD" and from_agent:
        values, unmapped = compile_opd_strata(rows, imp["period"])
    elif imp["report_type"] == "OPD":
        values, unmapped = compile_opd(rows, imp["period"])
    elif imp["report_type"] == "SURV":
        values, unmapped = compile_033b(rows, imp["period"])
    else:
        values, unmapped = compile_ipd(rows, imp["period"])
    if not values:
        err("Nothing to compile: no reported values fall within the selected period. "
            "For the weekly surveillance report, remember that a blank cell means "
            "'not reported' and is skipped - enter 0 where the true count is zero.")

    # Arithmetic the form implies but cannot enforce. 105:01's malaria chain is
    # five elements describing one pathway, each a subset of the last, and two
    # of the five have been blank at this facility every year since 2020.
    findings = consistency.check_opd(values) if imp["report_type"] == "OPD" else []

    m = mapping()
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO reports (import_id, type, facility_name, period, compiled_data, unmapped, generated_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (imp["id"], imp["report_type"], m["orgUnit"]["name"], imp["period"],
                 json.dumps(values), json.dumps(unmapped), user["sub"]),
            )
            report_id = cur.fetchone()["id"]
            cur.execute("UPDATE imported_data SET processing_status='COMPLETED' WHERE id=%s", (imp["id"],))
    db.audit(user["sub"], "Report compiled", {
        "report_id": report_id, "type": imp["report_type"], "period": imp["period"],
        "data_values": len(values), "unmapped_codes": len(unmapped),
    })
    return {"report_id": report_id, "data_values": len(values),
            "unmapped": unmapped, "consistency": findings}


# ---------------- reports ----------------

@app.get("/api/py/reports")
def list_reports(user: dict = Depends(current_user)):
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, type, facility_name, period, generated_by, generated_at, push_status,
                          jsonb_array_length(compiled_data) AS value_count
                   FROM reports ORDER BY id DESC LIMIT 100"""
            )
            return {"reports": [dict(r) for r in cur.fetchall()]}


@app.get("/api/py/reports/types")
def report_types_alias(user: dict = Depends(current_user)):
    """Alias for /api/py/report-types.

    MUST stay above /api/py/reports/{report_id}: FastAPI matches in declaration
    order, and below it this literal path is swallowed by the typed parameter
    and rejected with 422. It exists so a browser or deployment still holding an
    older bundle keeps working instead of failing with a validation error that
    looks nothing like a routing problem."""
    return report_types(user)


@app.get("/api/py/reports/{report_id}")
def get_report(report_id: int, user: dict = Depends(current_user)):
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM reports WHERE id=%s", (report_id,))
            r = cur.fetchone()
    if not r:
        err("Report not found", 404)
    return dict(r)


# ---------------- push to DHIS2 ----------------

class PushBody(BaseModel):
    report_id: int
    dry_run: bool = False


@app.post("/api/py/push")
def push(body: PushBody, user: dict = Depends(current_user)):
    require_role(user, "data_officer")
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM reports WHERE id=%s", (body.report_id,))
            r = cur.fetchone()
    if not r:
        err("Report not found", 404)
    values = r["compiled_data"]
    if isinstance(values, str):
        values = json.loads(values)
    try:
        payload = dhis2.build_payload(r["type"], r["period"], values)
        result = dhis2.submit(payload, dry_run=body.dry_run)
    except RuntimeError as exc:
        err(str(exc), 503)

    if body.dry_run:
        # A rehearsal must not be mistaken for a submission: the report's own
        # status is left untouched so it still reads as awaiting submission.
        result["dryRun"] = True
        db.audit(user["sub"], "Dry run against DHIS2", {
            "report_id": body.report_id, "type": r["type"], "period": r["period"],
            "result": result,
        })
        return {"push_status": "DRY_RUN", "result": result}

    status = "PUSHED" if result.get("accepted") else "FAILED"
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reports SET push_status=%s, push_response=%s WHERE id=%s",
                        (status, json.dumps(result), body.report_id))
    db.audit(user["sub"], "Report submitted to DHIS2", {
        "report_id": body.report_id, "type": r["type"], "period": r["period"], "result": result,
    })
    return {"push_status": status, "result": result}


@app.get("/api/py/dhis2/test")
def dhis2_test(user: dict = Depends(current_user)):
    require_role(user, "data_officer")
    try:
        info = dhis2.test_connection()
        return {"ok": True, "username": info.get("username"),
                "orgUnits": info.get("organisationUnits", [])}
    except RuntimeError as exc:
        err(str(exc), 503)
    except Exception as exc:
        err(f"Could not reach DHIS2: {exc}", 502)


@app.get("/api/py/dhis2/preflight")
def dhis2_preflight(report_type: str = "OPD", user: dict = Depends(current_user)):
    """Checks every condition DHIS2 requires before it will accept data values,
    to explain submissions that return SUCCESS yet ignore all values."""
    require_role(user, "data_officer")
    try:
        return dhis2.preflight(report_type)
    except RuntimeError as exc:
        err(str(exc), 503)
    except Exception as exc:
        err(f"Preflight failed: {exc}", 502)


# ---------------- audit ----------------

@app.get("/api/py/audit")
def audit_log(user: dict = Depends(current_user)):
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id, "user", action, details, timestamp FROM audit_log ORDER BY id DESC LIMIT 200')
            return {"entries": [dict(r) for r in cur.fetchall()]}


# ---------------- admin: users ----------------

class UserBody(BaseModel):
    email: str
    full_name: str = ""
    password: str
    role: str


@app.get("/api/py/users")
def list_users(user: dict = Depends(current_user)):
    require_role(user, "admin")
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, email, full_name, role, created_at FROM users ORDER BY id")
            return {"users": [dict(r) for r in cur.fetchall()]}


@app.post("/api/py/users")
def create_user(body: UserBody, user: dict = Depends(current_user)):
    require_role(user, "admin")
    if body.role not in ("admin", "data_officer", "viewer"):
        err("role must be admin, data_officer or viewer")
    if len(body.password) < 8:
        err("The password must be at least 8 characters long")
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE lower(email)=lower(%s)", (body.email,))
            if cur.fetchone():
                err("A user with this email address already exists", 409)
            cur.execute(
                "INSERT INTO users (email, full_name, password_hash, role) VALUES (%s,%s,%s,%s) RETURNING id",
                (body.email.strip(), body.full_name.strip(), db.hash_password(body.password), body.role),
            )
            uid = cur.fetchone()["id"]
    db.audit(user["sub"], "User created", {"email": body.email, "role": body.role})
    return {"id": uid}


@app.delete("/api/py/users/{user_id}")
def delete_user(user_id: int, user: dict = Depends(current_user)):
    require_role(user, "admin")
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id=%s AND lower(email)!=lower(%s)", (user_id, user["sub"]))
    db.audit(user["sub"], "User deleted", {"user_id": user_id})
    return {"ok": True}


# ---------------- meta ----------------

@app.get("/api/py/meta")
def meta(user: dict = Depends(current_user)):
    m = mapping()
    return {
        "orgUnit": m["orgUnit"],
        "dataSets": m["dataSets"],
        "reportTypes": m.get("reportTypes", {}),
        "instance": m["instance"],
        "dhis2_configured": bool(os.environ.get("DHIS2_USERNAME") or os.environ.get("DHIS2_PAT")),
        "db_configured": bool(os.environ.get("DATABASE_URL")),
    }


@app.post("/api/py/meta/refresh")
def meta_refresh(user: dict = Depends(current_user)):
    require_role(user, "admin")
    from _lib import validators as v, metadata, surveillance
    try:
        m = metadata.mapping(force_refresh=True)
        v._IPD_INDEX = None
        surveillance.reset_index()
        forms.reset_cache()
        counts = {
            "de_105": len(m["dataElements"].get("HMIS105_01", {})),
            "de_108": len(m["dataElements"].get("HMIS108", {})),
            "de_033b": len(m["dataElements"].get("HMIS033B", {})),
        }
        db.audit(user["sub"], "Metadata refreshed", counts)
        return {"ok": True, **counts}
    except RuntimeError as exc:
        err(str(exc), 503)


# ---------------- ClinicMaster extraction, via the on-premise agent ----------------

AGENT_CAPABLE = {"OPD"}   # report types the agent can extract today


class ExtractBody(BaseModel):
    report_type: str
    period: str


@app.post("/api/py/extract")
def request_extraction(body: ExtractBody, user: dict = Depends(current_user)):
    """Queue a pull from ClinicMaster. The agent inside the hospital picks this
    up on its next poll; nothing here reaches the database directly."""
    require_role(user, "data_officer")
    entry = report_type_entry(body.report_type)
    rt = body.report_type.upper()
    if rt not in AGENT_CAPABLE:
        err(f"{entry['short']} cannot be pulled from ClinicMaster yet. "
            f"Available today: " + ", ".join(sorted(AGENT_CAPABLE)))
    period = check_period(rt, body.period)

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            status = agentlib.agent_status(cur)
            job_id = agentlib.queue_job(cur, rt, period, user["sub"])
    db.audit(user["sub"], "ClinicMaster extraction requested",
             {"job_id": job_id, "type": rt, "period": period})
    return {
        "job_id": job_id,
        "state": "QUEUED",
        "agent_online": status["online"],
        "note": None if status["online"] else
                "No agent has reported in for over three minutes. The job is queued "
                "and will run as soon as the agent on the hospital network is started.",
    }


@app.get("/api/py/extract/{job_id}")
def extraction_status(job_id: int, user: dict = Depends(current_user)):
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            agentlib.ensure_tables(cur)
            cur.execute("""SELECT id, report_type, period, state, requested_by,
                                  requested_at, finished_at, agent, stratum_count,
                                  message, import_id
                           FROM extraction_jobs WHERE id=%s""", (job_id,))
            row = cur.fetchone()
    if not row:
        err("Extraction job not found", 404)
    out = dict(row)
    for k in ("requested_at", "finished_at"):
        out[k] = str(out[k]) if out[k] else None
    return out


@app.get("/api/py/agents")
def agents(user: dict = Depends(current_user)):
    """Whether an extraction agent is currently reachable, for the UI to show."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            return agentlib.agent_status(cur)


# --- agent-facing. Authenticated by AGENT_KEY, never by a user session. ---

@app.post("/api/py/agent/heartbeat")
def agent_heartbeat(body: dict, authorization: str = Header(default="")):
    agentlib.require_agent(authorization)
    ident = agentlib.fingerprint(agentlib.agent_key())
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            agentlib.record_heartbeat(cur, ident,
                                      str(body.get("version", ""))[:32],
                                      str(body.get("host", ""))[:128],
                                      str(body.get("note", ""))[:500])
    return {"ok": True, "agent": ident}


@app.get("/api/py/agent/next")
def agent_next_job(authorization: str = Header(default="")):
    """Hand the agent its next job. The response carries a report type and a
    period and nothing else - never SQL. The queries live in the agent's own
    package, so a compromised server cannot make it run arbitrary statements
    against a database of HIV records."""
    agentlib.require_agent(authorization)
    ident = agentlib.fingerprint(agentlib.agent_key())
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            agentlib.record_heartbeat(cur, ident, note="polling")
            job = agentlib.claim_job(cur, ident)
    if not job:
        return {"job": None}
    return {"job": {"id": job["id"], "report_type": job["report_type"],
                    "period": job["period"]}}


@app.post("/api/py/agent/jobs/{job_id}/result")
def agent_post_result(job_id: int, body: dict, authorization: str = Header(default="")):
    """Ingest anonymous strata from the agent and stage them for compilation."""
    agentlib.require_agent(authorization)

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            agentlib.ensure_tables(cur)
            cur.execute("SELECT * FROM extraction_jobs WHERE id=%s", (job_id,))
            job = cur.fetchone()
            if not job:
                err("Extraction job not found", 404)
            if job["state"] not in ("RUNNING", "QUEUED"):
                err(f"Job {job_id} is {job['state']} and no longer accepts a result", 409)

            if body.get("error"):
                cur.execute("""UPDATE extraction_jobs SET state='FAILED', finished_at=now(),
                               message=%s WHERE id=%s""",
                            (str(body["error"])[:2000], job_id))
                return {"ok": True, "state": "FAILED"}

            try:
                strata = agentlib.validate_strata(body.get("strata"))
            except ValueError as exc:
                cur.execute("""UPDATE extraction_jobs SET state='FAILED', finished_at=now(),
                               message=%s WHERE id=%s""", (str(exc)[:2000], job_id))
                err(f"Rejected: {exc}", 400)

            summary = agentlib.summarise(strata)
            rows = agentlib.strata_to_rows(strata)

            cur.execute("ALTER TABLE imported_data ADD COLUMN IF NOT EXISTS "
                        "source VARCHAR(32) NOT NULL DEFAULT 'UPLOAD'")
            cur.execute(
                """INSERT INTO imported_data
                   (file_name, report_type, period, row_count, error_count,
                    original_data, validation_errors, uploaded_by, processing_status, source)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (f"ClinicMaster {job['report_type']} {job['period']}",
                 job["report_type"], job["period"], summary["strata"], 0,
                 json.dumps(rows), json.dumps([]), job["requested_by"],
                 "PENDING", "AGENT"))
            import_id = cur.fetchone()["id"]

            cur.execute("""UPDATE extraction_jobs
                           SET state='DONE', finished_at=now(), strata=%s,
                               stratum_count=%s, import_id=%s, message=%s
                           WHERE id=%s""",
                        (json.dumps(summary), summary["strata"], import_id,
                         f"{summary['visits']:,} visits across {summary['strata']:,} strata",
                         job_id))

    db.audit(job["requested_by"], "ClinicMaster extraction completed", {
        "job_id": job_id, "import_id": import_id, "type": job["report_type"],
        "period": job["period"], **summary})
    return {"ok": True, "state": "DONE", "import_id": import_id, "summary": summary}


# ---------------- preview (any signed-in user, including viewers) ----------------

def _latest_report(report_type: str, period: str):
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, compiled_data, generated_at, generated_by, push_status
                   FROM reports WHERE type=%s AND period=%s
                   ORDER BY id DESC LIMIT 1""",
                (report_type.upper(), period),
            )
            return cur.fetchone()


@app.get("/api/py/report-types")
def report_types(user: dict = Depends(current_user)):
    """The eight registered reports, for the preview tabs and the upload picker.

    Deliberately NOT /api/py/reports/types: FastAPI matches routes in
    declaration order, so a literal path under /api/py/reports/ is shadowed by
    the earlier /api/py/reports/{report_id}, which then rejects 'types' as a
    non-integer with 422. A sibling path avoids the whole class of problem
    rather than relying on where in this file the route happens to sit."""
    out = []
    for key, e in mapping().get("reportTypes", {}).items():
        out.append({
            "type": key,
            "short": e["short"],
            "label": e["label"],
            "periodType": e["periodType"],
            "compiler": bool(e.get("compiler")),
            "defaultPeriod": periods.default_period(e["periodType"]),
            "formatHint": periods.FORMAT_HINT.get(e["periodType"], ""),
        })
    return {"reportTypes": out}


@app.get("/api/py/preview/{report_type}/status")
def preview_status(report_type: str, period: str, user: dict = Depends(current_user)):
    """Whether a compiled report exists for this report and period. Read-only:
    available to viewers, who cannot upload, compile or submit."""
    entry = report_type_entry(report_type)
    period = check_period(report_type, period)
    row = None
    try:
        row = _latest_report(report_type, period)
    except Exception:
        row = None
    values = (row or {}).get("compiled_data") or []
    if isinstance(values, str):
        values = json.loads(values)
    return {
        "type": report_type.upper(),
        "short": entry["short"],
        "label": entry["label"],
        "periodType": entry["periodType"],
        "period": period,
        "periodLabel": periods.describe(entry["periodType"], period),
        "compiler": bool(entry.get("compiler")),
        # How much of the form this compiler answers for, and how much of that
        # it filled. Reported even with no compiled report, because knowing that
        # 4,060 of 6,329 cells are ours is useful before anything is compiled.
        "coverage": coverage.zero_fill(values, report_type)[1],
        "report": None if not row else {
            "id": row["id"],
            "values": len(values),
            "generated_at": str(row.get("generated_at") or ""),
            "generated_by": row.get("generated_by"),
            "push_status": row.get("push_status"),
        },
    }


@app.get("/api/py/preview/{report_type}")
def preview(report_type: str, period: str, user: dict = Depends(current_user)):
    """The official DHIS2 form for this report, rendered read-only with any
    compiled values in place. Served as a complete HTML document for a sandboxed
    iframe - every field is an inert span and no script survives sanitisation."""
    entry = report_type_entry(report_type)
    period = check_period(report_type, period)

    row = None
    try:
        row = _latest_report(report_type, period)
    except Exception:
        row = None

    values = (row or {}).get("compiled_data") or []
    if isinstance(values, str):
        values = json.loads(values)

    # Show a zero wherever this compiler answers for a cell and counted nothing.
    # Only for a report that was actually compiled: zero-filling a blank form
    # would assert that nothing happened all month, which is a different and
    # much larger claim than "we compiled this and found none".
    shown, cov = (values, {}) if not row else coverage.zero_fill(values, report_type)

    try:
        doc = forms.render_document(
            report_type=report_type.upper(),
            period=period,
            period_label=periods.describe(entry["periodType"], period),
            values=forms.values_map(shown),
            meta={"report_id": (row or {}).get("id"),
                  "push_status": (row or {}).get("push_status"),
                  "imputed": forms.imputed_keys(shown),
                  "coverage": cov},
        )
    except RuntimeError as exc:
        err(str(exc), 503)
    except requests.RequestException as exc:
        err(f"Could not fetch the official form from DHIS2: {exc}", 502)

    return Response(content=doc, media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store",
                             "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@app.post("/api/py/forms/refresh")
def forms_refresh(user: dict = Depends(current_user)):
    require_role(user, "admin")
    forms.reset_cache()
    try:
        result = forms.refresh_all()
    except RuntimeError as exc:
        err(str(exc), 503)
    db.audit(user["sub"], "Form layouts refreshed", result)
    return {"ok": True, "slots": result}


@app.get("/api/py/scripts/{report_type}")
def extraction_script(report_type: str, period: str = "", os: str = "windows",
                      user: dict = Depends(current_user)):
    """A ready-to-run extraction script for one report, period and platform.

    The period is baked into the SQL as literals, so a script downloaded for
    June cannot be run against May by accident."""
    require_role(user, "data_officer")
    # Utility scripts describe the database rather than extract a report, so
    # they carry no period and no report type to validate.
    if report_type.lower() in extract_scripts.UTILITIES:
        period_type, label = "Monthly", ""
    else:
        entry = report_type_entry(report_type)
        period = check_period(report_type, period)
        period_type, label = entry["periodType"], entry["short"]
    try:
        name, text = extract_scripts.generate(
            report_type=report_type, period=period, os_key=os,
            period_type=period_type, report_label=label)
    except ValueError as exc:
        err(str(exc))
    return Response(
        content=text, media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"',
                 "Cache-Control": "no-store"})


@app.get("/api/py/scripts")
def extraction_script_options(user: dict = Depends(current_user)):
    """Which platforms and reports the script generator supports."""
    return {
        "operatingSystems": [
            {"key": k, **v} for k, v in extract_scripts.OS_CHOICES.items()
        ],
        "reports": sorted(extract_scripts.SCRIPTABLE),
        # Every registered report, with the reason where there is no script.
        # A report simply missing from the picker reads as a fault in the app;
        # a report listed with its reason reads as a plan.
        "reportStatus": [
            {"type": rt,
             "short": entry["short"],
             "label": entry["label"],
             "periodType": entry["periodType"],
             "available": rt in extract_scripts.SCRIPTABLE,
             "reason": extract_scripts.NOT_SCRIPTABLE.get(rt, "")}
            for rt, entry in mapping()["reportTypes"].items()
        ],
        "utilities": [{"key": k, **v} for k, v in extract_scripts.UTILITIES.items()],
    }


@app.get("/api/py/templates/033b")
def template_033b(user: dict = Depends(current_user)):
    """The blank 033B tally, generated from live metadata rather than a checked-in
    file, so it can never drift from what the national instance will accept."""
    try:
        csv_text = template_csv()
    except RuntimeError as exc:
        err(str(exc), 503)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="HMIS_033B_Weekly_Template.csv"'},
    )


@app.get("/api/py/period/week")
def week_label(period: str):
    """Human-readable date range for a weekly period, for the UI to display."""
    if not parse_week_period(period):
        err("period must be in YYYYWnn format, for example 2026W34")
    return {"period": period.upper(), "label": describe_week(period.upper())}


@app.get("/api/py/health")
def health():
    return {"ok": True}
