# HMIS Report Compiler — Jinja Regional Referral Hospital

A web application that compiles Uganda eHMIS monthly reports — 105:01 (Outpatient) and 108 (Inpatient) — from raw register extracts (CSV/Excel) and submits the aggregated data to the national DHIS2 instance (hmis.health.go.ug) via the dataValueSets API.

## Architecture

- **Frontend**: Next.js 14 (App Router), deployed on Vercel.
- **Backend**: FastAPI (Python) as a Vercel serverless function under `/api/py/*`.
- **Database**: Neon Postgres (staging data, compiled reports, users, audit trail, metadata cache).
- **DHIS2 metadata**: dataset, organisation unit and disaggregation identifiers verified against the live national instance are embedded in `api/_lib/metadata.py`; the full data element listings are fetched from the DHIS2 API on first use and cached in Postgres.

## Environment variables (Vercel → Project → Settings → Environment Variables)

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Neon Postgres connection string (pooled) |
| `JWT_SECRET` | Long random string for session tokens |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Seeds the first System Admin account when the users table is empty |
| `DHIS2_BASE_URL` | Defaults to `https://hmis.health.go.ug` |
| `DHIS2_USERNAME` / `DHIS2_PASSWORD` | DHIS2 account with data entry rights for the facility (or use `DHIS2_PAT` for a personal access token) |

## Workflow

1. **Upload** — Data Officer uploads the monthly register extract (CSV/XLSX) using the published templates (`/templates/...`).
2. **Validate** — mandatory fields, data types, dates, diagnosis codes and ward names are checked; failing rows are listed and excluded.
3. **Compile** — records are aggregated: OPD by diagnosis × age band (0–28d, 29d–4y, 5–9y, 10–19y, 20+) × sex; IPD ward services (CI02 admissions, CI03 deaths, CI04 patient days, CI05 average length of stay) by ward, and Section 6 diagnoses (Cases/Deaths) by age band × sex.
4. **Preview** — the compiled report is displayed for review.
5. **Submit** — a `dataValueSet` payload is POSTed to DHIS2 with retry and full response handling; the outcome is recorded in the audit trail.

## Roles

- **System Admin** — user management, configuration, metadata refresh.
- **Data Officer** — upload, compile, submit.
- **Supervisor (Viewer)** — view reports and the audit trail.

## Local development

```bash
npm install
pip install -r requirements.txt uvicorn
npm run fastapi-dev   # FastAPI on :8000
npm run dev           # Next.js on :3000 (proxies /api/py to :8000)
python scripts/generate_sample_data.py .   # sample files for testing
```
