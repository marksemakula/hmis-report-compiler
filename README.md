# HMIS Report Compiler — Jinja Regional Referral Hospital

A web application that compiles Uganda eHMIS reports — 105:01 (Outpatient, monthly), 108 (Inpatient, monthly) and 033B (Weekly Epidemiological Surveillance) — from raw register extracts or weekly tallies (CSV/Excel) and submits the aggregated data to the national DHIS2 instance (hmis.health.go.ug) via the dataValueSets API.

## Reports

All eight are registered and previewable. "Compile" marks those that can be turned into data values and submitted today.

| Key | Report | Data set | Cadence | Period | Compile |
| --- | --- | --- | --- | --- | --- |
| `OPD` | HMIS 105:01 — OPD (Attendance, Referrals, Conditions, TB, Nutrition) | `RtEYsASU7PG` | Monthly | `YYYYMM` | yes |
| `MCH` | HMIS 105:02-03 — OPD (MCH, FP, EID, EPI & HEPB) | `ic1BSWhGOso` | Monthly | `YYYYMM` | — |
| `HTS` | HMIS 105:04-05 — OPD (HTS & SMC) | `nGkMm2VBT4G` | Monthly | `YYYYMM` | — |
| `PALL` | HMIS 105C — Palliative Care | `V6TqjXm5sQy` | Monthly | `YYYYMM` | — |
| `IPD` | HMIS 108 — Inpatient | `EBqVAQRmiPm` | Monthly | `YYYYMM` | yes |
| `SURV` | HMIS 033b — Weekly Epidemiological Surveillance | `C4oUitImBPK` | Weekly | `YYYYWnn` | yes |
| `HIV` | HMIS 106a:01-02 — HIV Quarterly | `dFRD2A5fdvn` | Quarterly | `YYYYQn` | — |
| `TBL` | HMIS 106a:03 — TB/Leprosy Quarterly | `DFMoIONIalm` | Quarterly | `YYYYQn` | — |

## Preview

Every one of the eight data sets uses a **custom** DHIS2 entry form: the Ministry supplies the HTML of the paper form, with one `<input>` per cell identified as `{dataElement}-{categoryOptionCombo}-val` — the same key our compiled data values carry.

The **Preview** tab therefore renders the genuine official form rather than a table of our own devising, with compiled figures dropped into place. Two consequences worth having:

- It looks exactly like the entry screen the QA team already knows, which is what makes it usable for checking a report before submission.
- When the Ministry revises a form, the preview follows on the next refresh. Nothing transcribes 2,752 data elements by hand.

Access is any signed-in user, **Viewer included**. Viewers get the Preview, Reports and Audit tabs; they cannot upload, compile or submit. A period with no compiled report shows the blank form, so the tab doubles as a reference library of the eight forms.

**Safety.** The form HTML is third-party. At cache time every `<script>`, inline event handler and `javascript:` URL is stripped and every field becomes an inert `<span>`; the document is then served into a `sandbox=""` iframe under a restrictive Content-Security-Policy. Nothing in a form can execute, and no value can be edited. Values are HTML-escaped on injection.

Layouts are cached in Postgres (`form_cache`) because 105:01 alone is over half a megabyte. Admins can re-fetch them with `POST /api/py/forms/refresh`.

## Roadmap

- **Phase 1 — preview and registration.** *Complete.* All eight data sets registered with their official names, cadences and identifiers; the three period formats handled; read-only preview of the official form for every report, open to Viewers.
- **Phase 2 — the five remaining compilers.** `MCH`, `HTS`, `PALL`, `HIV`, `TBL`. Each needs its own input shape and aggregation rules; `PALL` is smallest at 24 elements and is the sensible first.
- **Phase 3 — direct ClinicMaster connector.** Replace the CSV round-trip with a query run from the compiler when it is on the hospital network. Note that ClinicMaster runs on **Microsoft SQL Server**, not MySQL — the driver will be `pyodbc` or `pymssql`, and the connection must be read-only and credential-scoped.
- **Phase 4 — validation and QA.** Cross-check compiled figures against what DHIS2 already holds for the period, and flag variances before submission.

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
5. **Dry run** *(optional)* — the same payload is sent with `?dryRun=true`. DHIS2 validates it and returns the identical import summary, but writes nothing. Every conflict a real submission would raise appears exactly as it would. The report's status is left untouched, so a rehearsal is never mistaken for a submission.
6. **Submit** — a `dataValueSet` payload is POSTed to DHIS2 with retry and full response handling; the outcome is recorded in the audit trail.

## Testing a change before it is pushed

Everything up to and including **Compile & Preview** is local: nothing reaches the national instance. Only *Submit* writes. In order of cost:

| Step | Command | Needs |
| --- | --- | --- |
| Unit checks | `python scripts/test_surveillance.py` | nothing |
| Form and period checks | `python scripts/test_forms.py` | nothing |
| Routing check | `python scripts/test_routes.py` | nothing |
| Import check | `python -m py_compile api/index.py api/_lib/*.py` | nothing |
| Local app | `npm run fastapi-dev` + `npm run dev` | `DATABASE_URL` |
| Metadata reachable | `GET /api/py/templates/033b` | DHIS2 credentials |
| Submission rehearsal | **Dry run** button, or `POST /api/py/push {"report_id":N,"dry_run":true}` | DHIS2 credentials |
| Permissions check | `GET /api/py/dhis2/preflight?report_type=SURV` | DHIS2 credentials |

`preflight` is read-only and answers the question that usually explains a submission which returns SUCCESS yet writes nothing: whether the data set is assigned to the org unit, whether the account holds data-write sharing, and whether the period is open.

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

`scripts/test_surveillance.py` stubs the DHIS2 metadata with a fixture that reproduces the national instance's naming inconsistencies (both `033B-` and `033b-` prefixes, and one element whose code is not followed by a full stop), then exercises ISO week handling, tally validation, compilation and template generation.

`scripts/test_forms.py` checks the eight registrations, the element-name prefixes across all data set families, all three period cadences, and the form sanitiser — which it feeds a deliberately hostile form to confirm no script, handler or `javascript:` URL survives and that injected values are escaped.

`scripts/test_routes.py` parses the route declarations and fails if a literal path is shadowed by an earlier parameterised sibling. FastAPI matches in declaration order, so `/api/py/reports/types` declared after `/api/py/reports/{report_id}` is unreachable and returns **422**, not 404 — which reads like a validation bug rather than a routing one. That is why the report list lives at `/api/py/report-types`. The check also confirms every `/api/py/` URL the front end calls resolves to a declared route.

All three run offline in about a second and need neither a database nor credentials.
