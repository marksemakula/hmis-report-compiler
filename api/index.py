"""HMIS Report Compiler — FastAPI backend (deployed as a Vercel Python function)."""
import json
import os
import re
import sys

sys.path.append(os.path.dirname(__file__))

import requests

from fastapi import FastAPI, HTTPException, Request, Response, Depends
from pydantic import BaseModel

from _lib import db
from _lib.auth import issue_token, current_user, require_role
from _lib.validators import parse_file, validate_rows, mapping, OPD_COLUMNS, IPD_COLUMNS, OPD_COLUMNS, IPD_COLUMNS
from _lib.compiler import compile_opd, compile_ipd
from _lib import dhis2

app = FastAPI(title="HMIS Report Compiler", docs_url=None, redoc_url=None)


def err(detail, code=400):
    raise HTTPException(status_code=code, detail=detail)


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


BLOB_URL_RE = re.compile(r"^https://[a-z0-9]+\\.(private|public)\\.blob\\.vercel-storage\\.com/")


BLOB_URL_RE = re.compile(r"^https://[a-z0-9]+\.(private|public)\.blob\.vercel-storage\.com/")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class UploadBody(BaseModel):
    blob_url: str
    filename: str
    report_type: str
    period: str


@app.post("/api/py/upload")
def upload(body: UploadBody, user: dict = Depends(current_user)):
    """Ingest a register extract previously uploaded to Vercel Blob.

    The browser uploads the file directly to the private Blob store (client
    upload), then posts the blob URL here. This bypasses the hard 4.5 MB
    request-body limit on Vercel serverless functions.
    """
    require_role(user, "data_officer")
    if body.report_type not in ("OPD", "IPD"):
        err("report_type must be OPD or IPD")
    period = body.period
    if not (len(period) == 6 and period.isdigit() and 1 <= int(period[4:]) <= 12):
        err("period must be in YYYYMM format")
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
    expected = OPD_COLUMNS if body.report_type == "OPD" else IPD_COLUMNS
    try:
        rows = parse_file(body.filename, content, expected_columns=expected)
    except Exception as exc:
        err(f"The file could not be parsed: {exc}")
    if not rows:
        err("The file contains no data rows. Check that the register was "
            "exported into a sheet whose first row has the template headers.")
    clean, errors = validate_rows(body.report_type, rows, period)
    in_period = sum(1 for r in clean if r["in_period"])

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO imported_data
                   (file_name, report_type, period, row_count, error_count, original_data, validation_errors, uploaded_by, processing_status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (body.filename, body.report_type, period, len(rows), len(errors),
                 json.dumps(clean), json.dumps(errors), user["sub"],
                 "PENDING" if not errors else "PENDING"),
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
    if imp["report_type"] == "OPD":
        values, unmapped = compile_opd(rows, imp["period"])
    else:
        values, unmapped = compile_ipd(rows, imp["period"])
    if not values:
        err("No records fall within the selected reporting period, so there is nothing to compile")

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
    return {"report_id": report_id, "data_values": len(values), "unmapped": unmapped}


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
        result = dhis2.submit(payload)
    except RuntimeError as exc:
        err(str(exc), 503)
    status = "PUSHED" if result.get("status") in ("SUCCESS", "OK", "WARNING") else "FAILED"
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
        "instance": m["instance"],
        "dhis2_configured": bool(os.environ.get("DHIS2_USERNAME") or os.environ.get("DHIS2_PAT")),
        "db_configured": bool(os.environ.get("DATABASE_URL")),
    }


@app.post("/api/py/meta/refresh")
def meta_refresh(user: dict = Depends(current_user)):
    require_role(user, "admin")
    from _lib import validators as v, metadata
    try:
        m = metadata.mapping(force_refresh=True)
        v._IPD_INDEX = None
        db.audit(user["sub"], "Metadata refreshed", {"de_105": len(m["dataElements"]["HMIS105_01"]),
                                                     "de_108": len(m["dataElements"]["HMIS108"])})
        return {"ok": True, "de_105": len(m["dataElements"]["HMIS105_01"]),
                "de_108": len(m["dataElements"]["HMIS108"])}
    except RuntimeError as exc:
        err(str(exc), 503)


@app.get("/api/py/health")
def health():
    return {"ok": True}
