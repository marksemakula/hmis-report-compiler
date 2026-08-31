# JRRH extraction agent

A small program that runs **inside the hospital network** and lets the compiler pull figures from ClinicMaster without the database ever being exposed.

## Why it exists

ClinicMaster is at `172.20.0.230`, a private address on the hospital LAN. The compiler runs on Vercel, on the public internet, and cannot route to a private address. No configuration changes that.

Rather than opening a hole in the firewall or tunnelling the database out, this agent reaches out:

```
Hospital LAN                                    Internet
──────────────────────────────────────────────────────────
  ClinicMaster 172.20.0.230                   Vercel app
        ▲                                          ▲
        │ read-only T-SQL                          │ HTTPS
        │                                          │ outbound only
    jrrh-agent  ────────────────────────────────────┘
    polls for jobs · aggregates here · posts counts
```

Three things follow, and they are the point:

- **No inbound firewall rule.** The agent only makes outbound HTTPS calls.
- **No database credential reaches Vercel.** They live only on this machine.
- **No patient-level data leaves the hospital.** The agent posts *strata* — counts by diagnosis, age band, sex and visit type. Never rows. The server rejects any payload carrying a patient identifier, so a mistake here fails loudly rather than quietly leaking.

The server also never sends SQL. A job says only "105:01 for June 2026"; the queries live in `queries.py` in this repository. A compromised or spoofed server cannot make this agent run arbitrary statements against a database of HIV and TB records.

## Requirements

- Python 3.9 or later
- A SQL Server driver: `pip install pymssql` (self-contained, usually easier) or `pip install pyodbc` (needs Microsoft's ODBC driver installed separately)
- A **read-only** SQL login on ClinicMaster. Do not use a login with write rights; the agent refuses to run anything that is not a read, but a read-only account means the question never arises.

## Setup

```bash
cd agent
pip install -r requirements.txt
cp .env.example .env      # then edit it
python jrrh_agent.py --check
```

`--check` tests both connections and prints whether the diagnosis columns have been confirmed. Nothing is extracted.

## Configuration

`.env` beside the script, or ordinary environment variables:

| Variable | Meaning |
| --- | --- |
| `COMPILER_URL` | `https://hmis-report-compiler.vercel.app` |
| `AGENT_KEY` | The same secret set as `AGENT_KEY` in the Vercel project. At least 24 random characters. |
| `CM_SERVER` | `172.20.0.230` |
| `CM_DATABASE` | `ClinicMasterMOH` |
| `CM_USER` / `CM_PASSWORD` | The read-only login |
| `POLL_SECONDS` | How often to ask for work. Default 20. |

Generate a key with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## Running

```bash
python jrrh_agent.py            # poll continuously — the normal mode
python jrrh_agent.py --once     # run any waiting job, then stop
python jrrh_agent.py --schema   # print ClinicMaster columns and exit
python jrrh_agent.py --check    # test connections and exit
```

While it is polling, the compiler shows **agent online** beside the *Pull from ClinicMaster* option. A Data Officer picks a report and period, clicks the button, and the agent picks the job up within `POLL_SECONDS`.

To keep it running unattended use whatever the host machine offers — a Windows scheduled task at logon, a `launchd` job on macOS, or `systemd` on Linux.

## One thing still to finish

`DIAGNOSIS_SOURCE` in `queries.py` has `confirmed: False`. The `Diagnosis` and `Diseases` column names were never established, so until they are the agent extracts **attendance only** — OPD new and re-attendance by age band and sex — and says so in the job notes rather than guessing at column names and producing a report with no conditions in it.

To finish it:

```bash
python jrrh_agent.py --schema
```

Match the printed columns against `DIAGNOSIS_SOURCE`, correct the four names, set `confirmed` to `True`, and run `python ../scripts/test_agent.py` to confirm nothing else broke.

## Checking the figures

The agent path and the upload path must produce identical numbers, or the result depends on how the data arrived — which is indefensible to the Ministry. `scripts/test_agent.py` asserts this directly: it compiles fifty visits both ways and requires every data value to match.

For real reassurance, take a month you have already compiled from a CSV, pull the same month through the agent, and compare the two reports in the Reports tab. They should agree exactly.
