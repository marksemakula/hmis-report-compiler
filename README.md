# HMIS Report Compiler — Jinja Regional Referral Hospital

A web application that compiles Uganda eHMIS reports — 105:01 (Outpatient, monthly), 108 (Inpatient, monthly) and 033B (Weekly Epidemiological Surveillance) — from raw register extracts or weekly tallies (CSV/Excel) and submits the aggregated data to the national DHIS2 instance (hmis.health.go.ug) via the dataValueSets API.

## Reports

| Report | Data set | Cadence | Period format | Input |
| --- | --- | --- | --- | --- |
| eHMIS 105:01 — Outpatient | `RtEYsASU7PG` | Monthly | `YYYYMM` | Line-listed register extract |
| eHMIS 108 — Inpatient | `EBqVAQRmiPm` | Monthly | `YYYYMM` | Line-listed register extract |
| eHMIS 033B — Weekly Surveillance | `C4oUitImBPK` | Weekly | `YYYYWnn` | Two-column tally (`Code`, `Value`) |

### A note on 033B

033B is structurally unlike the other two. All 239 of its data elements sit on the **default** category combination — there is no age or sex disaggregation to compute — so the import is a tally rather than a line list, and compilation is a direct translation from HMIS code to data element.

This matters because a good part of the form cannot come from any register: tracer medicine and ARV stock balances, GeneXpert cartridges remaining and modules working are physical observations. The workflow is therefore:

1. Run `scripts/sql/07_period_extract.sql` against ClinicMaster for the week in question. It emits `Code,Value` rows for everything the EMR can answer.
2. Export that grid as CSV, open it beside the blank template, and key in the stock and equipment figures the query cannot supply.
3. Upload, validate, compile, submit.

Two conventions are worth holding on to. A **blank** value means *not reported* and is skipped; a **zero** means *reported as zero*. DHIS2 stores those differently, and conflating them misrepresents the facility. And periods are **ISO-8601** weeks: Monday to Sunday, with week 1 being the week containing 4 January. `DATEPART(week, …)` in SQL Server does not follow ISO — `DATEPART(ISO_WEEK, …)` does, and the extraction script uses it throughout.

The blank 033B template is generated from live DHIS2 metadata at `/api/py/templates/033b` rather than checked in, so it cannot drift from what the national instance will accept.

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
python scripts/test_surveillance.py        # 033B checks — no DB or network needed
```

`scripts/test_surveillance.py` stubs the DHIS2 metadata with a fixture that reproduces the national instance's naming inconsistencies (both `033B-` and `033b-` prefixes, and one element whose code is not followed by a full stop), then exercises ISO week handling, tally validation, compilation and template generation. It runs offline in under a second.
