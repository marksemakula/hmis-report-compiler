"""Database layer - Neon Postgres via psycopg2. Tables are created on first use."""
import os
import json
import hashlib
import secrets
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL DEFAULT '',
    password_hash VARCHAR(512) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS imported_data (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(512) NOT NULL,
    report_type VARCHAR(8) NOT NULL,
    period VARCHAR(16) NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    original_data JSONB NOT NULL DEFAULT '[]',
    validation_errors JSONB NOT NULL DEFAULT '[]',
    uploaded_by VARCHAR(255) NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processing_status VARCHAR(16) NOT NULL DEFAULT 'PENDING'
);
CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    import_id INTEGER REFERENCES imported_data(id),
    type VARCHAR(8) NOT NULL,
    facility_name VARCHAR(255) NOT NULL,
    period VARCHAR(16) NOT NULL,
    compiled_data JSONB NOT NULL,
    unmapped JSONB NOT NULL DEFAULT '[]',
    generated_by VARCHAR(255) NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    push_status VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
    push_response JSONB
);
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    "user" VARCHAR(255) NOT NULL,
    action VARCHAR(64) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# CREATE TABLE IF NOT EXISTS leaves an existing table alone, so a column that
# was too narrow when the table was first made stays too narrow forever. These
# run on every start and are no-ops once applied.
#
# period was VARCHAR(6), sized for a monthly identifier like 202607. A weekly
# one is seven characters - 2026W35 - so uploading a weekly surveillance tally
# raised StringDataRightTruncation and the whole upload failed. The cruel detail
# is that weeks 1 to 9 are six characters and worked, so the fault only appeared
# from week 10 onwards and looked intermittent.
_MIGRATIONS = """
ALTER TABLE imported_data ALTER COLUMN period TYPE VARCHAR(16);
ALTER TABLE reports       ALTER COLUMN period TYPE VARCHAR(16);
"""

_initialised = False


def _dsn():
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not configured. Add it in Vercel project settings.")
    return dsn


@contextmanager
def get_conn():
    global _initialised
    conn = psycopg2.connect(_dsn(), cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if not _initialised:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA)
                cur.execute(_MIGRATIONS)
            conn.commit()
            _seed_admin(conn)
            _initialised = True
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------- password hashing (stdlib PBKDF2) ----------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"pbkdf2${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
        return secrets.compare_digest(candidate, digest)
    except Exception:
        return False


def _seed_admin(conn):
    email = os.environ.get("ADMIN_EMAIL", "admin@jinjarrh.go.ug")
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        return
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM users")
        if cur.fetchone()["n"] == 0:
            cur.execute(
                "INSERT INTO users (email, full_name, password_hash, role) VALUES (%s,%s,%s,'admin')",
                (email, "System Administrator", hash_password(password)),
            )
    conn.commit()


def audit(user: str, action: str, details: dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO audit_log ("user", action, details) VALUES (%s,%s,%s)',
                (user, action, json.dumps(details)),
            )
