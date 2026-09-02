# The CPHL / ALIS laboratory integration

Findings from `scripts/sql/10_labhie_payload_discovery.sql`, run against
`ClinicMasterMOH` on 172.20.0.230, 2 September 2026.

## What we were told, and what is true

We were pointed at `http://172.20.0.137/labhie/labrequest` and a user guide.
The URL returns a Laravel `MethodNotAllowedHttpException` on GET, the guide is
an end-user manual with no endpoint list, and `cphlgit/alis-v4` is private. On
that evidence the API looked undocumented.

It is not undocumented. It is **HL7 FHIR**, and ClinicMaster has been speaking
it for years. The specification was in our own database all along, written by
the integration itself.

## The wire format

**Request** - a FHIR transaction bundle. Three top-level keys, present on all
2,000 messages sampled:

| Key | JSON type |
|---|---|
| `resourceType` | string - `"Bundle"` |
| `type` | string - `"transaction"` |
| `entry` | array of objects |

Median payload is 7,988 bytes; the largest seen is 19,713. 103,171 of the
104,137 stored messages are valid JSON.

**Response** - a FHIR transaction-response bundle:

```json
{
  "resourceType": "Bundle",
  "id": "fd2b6165-990f-477b-87ed-e4aa1c5f5098",
  "type": "transaction-response",
  "entry": [
    {
      "resource": {
        "resourceType": "Parameters",
        "id": "22000509007-26604007",
        "parameter": [{ "name": "visitid", "valueInteger": 207042 }]
      },
      "response": { "status": "201 Created", "lastModified": "..." }
    }
  ]
}
```

ClinicMaster stores this verbatim in `INTLabRequestDetails.Message`, prefixed
with the literal string `Success`.

Three things are worth noting about it.

**The entry `id` is a composite key.** `22000509007-26604007` is
`SpecimenNo` + `-` + `TestCode`, and both halves match columns on
`INTLabRequestDetails`. The test codes are SNOMED CT where a SNOMED concept
exists (`26604007` is a full blood count) and local codes otherwise
(`86328` is five digits and cannot be SNOMED). Any client we write must
tolerate both.

**The response returns a `visitid`.** ALIS allocates its own integer visit
identifier and hands it back. That is the handle for retrieving results later.

**The bundle `id` never changes.** Every one of the 103,171 responses carries
`fd2b6165-990f-477b-87ed-e4aa1c5f5098`. A transaction-response bundle is meant
to be uniquely identified; ALIS appears to be returning a hardcoded constant.
Harmless to us - we key on the entry ids - but worth reporting to CPHL, since
it makes their own responses impossible to correlate.

### The empty-entry response

97,908 of the responses have `"entry": []` - accepted, but nothing created.
Only a few dozen carry entries. This needs one confirmation before we rely on
it: the most likely reading is that a bundle is posted once per specimen
carrying all of its tests, the same response text is stamped onto each of that
specimen's detail rows, and an empty array means a resend of something ALIS
already held. It is equally consistent with a silent rejection. Section 8 of
script 11 will tell us which, by showing whether results actually came back
for the specimens that got an empty response.

## Two endpoints, not one

| Path | Table | Rows | State |
|---|---|---|---|
| the working one | `INTLabRequestDetails` (`AgentNo = 'ALIS'`) | 104,137 | 100,806 synced, 3,331 pending |
| `labhie` | `INTHIELabRequestDetails` | 3 | 0 results ever returned |

The URL we were given, `/labhie/labrequest`, corresponds to the second row.
JRRH has attempted it three times and never received a result. The integration
that actually carries this hospital's laboratory traffic is the older ALIS
agent, and `INTHIELabResults` is empty.

This reframes the work. Building a client for `labhie` means being the first
site to make it work, without documentation, against a Laravel 6 application
that is three years past end of life. Reading what the existing integration has
already stored costs nothing and is available today.

## Where the results already are

| Table | Rows | Grain |
|---|---|---|
| `LabResults` | 28,228 | one row per test - **the clinical record** |
| `LabResultsEXT` | 250,701 | one row per analyte - **where the values are** |
| `INTLabResults` | 28,214 | integration staging |
| `INTLabResultsEXT` | 250,701 | integration staging |
| `INTTestCMIntegrationResponse` | 333,895 | raw `payloadmsg` |

Read the unprefixed pair. The `INT` tables are integration staging; `LabResults`
holds fourteen results the integration never carried.

**The value is not on the parent row.** `LabResults.Result` is blank for every
reportable test - 3,724 empty malaria smears, 222 empty HIV serologies. The
parent is a container and the value sits one level down in `LabResultsEXT`, one
row per analyte. The proof is in the same output: sub-test `01 Detection`
appears exactly 3,724 times, matching the blank malaria parents one for one.
`ResultFlagID` is no help either - it is `104NA` on all 28,214 rows.

**The join back to a visit holds.** `LabRequests` carries both `SpecimenNo` and
`VisitNo`, and 28,191 of the 28,214 results reconcile to it - 99.9 per cent. So
`LabResults → LabRequests → Visits → Patients` yields the age and sex every
laboratory cell on an HMIS form is disaggregated by. `LabRequestsIPD` (46,805
rows) carries a specimen but no visit and reaches the patient by some other
route, which script 12 identifies.

**The history is short.** 2023: 389 results. 2024: 1,483. 2025: 6,035. 2026:
20,307. The integration only came into real use this year, so laboratory fields
before 2026 will be sparse whatever we do.

**Consequence for the compiler.** No network connector is required to fill the
laboratory fields on HMIS 105 and 106a. The on-premise agent reads
`INTLabResults` exactly as it reads `Visits`, aggregates on site, and posts
counts. The private-LAN problem we were bracing for does not arise, because the
data never had to cross a network we could not route to.

A client for `labhie` remains worth building later, for *ordering* tests and for
results that ALIS holds but ClinicMaster has not pulled. It is no longer on the
critical path for reporting.

## The test catalogue

Fifty-nine distinct tests have produced results. Codes are SNOMED CT where a
concept exists and local otherwise. Those that matter to the HMIS forms:

| Code | Test | Results |
|---|---|---|
| `372071003` | BS for mps (Malaria) | 3,773 |
| `407727009` | Malaria RDT | 324 |
| `165813002` | HIV serology | 222 |
| `313660005` | CD4 count | 152 |
| `9000001` | Xpert MTB/Rif | 127 |
| `121980003` | CrAg | 116 |
| `951277` | Urine TB LAM | 84 |
| `47758006` | HBsAg | 562 |
| `269829001` | TPHA | 451 |
| `19869000` | RPR | 157 |
| `399256002` | HIV-1 DNA PCR | 5 |
| `28804003` | HIV drug resistance | 2 |
| `315124004` | HIV viral load | 1 |

Two things follow. The HIV drug-resistance count of 2 independently corroborates
the HIVDR data-call return, which reported one result in 2025 and one in 2026.
And HIV testing volume is *not* principally in the laboratory tables - 222
serologies against 2,198 rows in `PreTestingCounseling` - so HMIS 105:04-05 must
be compiled from the HTS tables, not from the lab.

## A defect worth reporting to the ClinicMaster vendor

Sixty-six results are stuck with `SyncStatus = 0` and this error:

> Procedure or function 'uspUpdateLabResults' expects parameter
> '@DateResultsReceived', which was not supplied.

A stored procedure's signature changed and its caller was not updated. These are
laboratory results that came back from CPHL and never attached to the patient's
record. It is a clinical-safety issue, not just a reporting one, and it is
plausibly a regression from the 6.5.0 upgrade.

## Open questions, answered by script 12

1. The result vocabulary, read from `LabResultsEXT` where the values actually
   are, and from `LabPossibleResults` (43 rows) if that is the controlled list.
2. How `LabRequestsIPD` reaches a patient.
3. How many results in each year can be traced to a visit, and therefore
   reported at all.

## For CPHL

Three findings from the Ignition debug page the application served publicly:

- Laravel **6.20.45** - security support ended September 2022.
- PHP **7.4.3** - security support ended November 2022.
- `APP_DEBUG` is **enabled in production**. The exception page exposes the
  environment, including database credentials, to any unauthenticated visitor
  who triggers an error. This is the most urgent of the three.

A request worth making of them: `routes/api.php` and the `LabRequest` form
request class from the private repository. Those two files are the entire
specification we have had to reverse-engineer.

## Handling rules that apply to this work

- `INTLabRequestDetails.JsonMessage` contains patient data - names, numbers,
  dates of birth. Script 10 reads key names only and never values. Any future
  script that touches it must do the same.
- The ALIS account credential supplied in conversation should be rotated. It is
  not stored in this repository and will not be; the connector, when it is
  built, reads it from an environment variable.
- `INTAgents` configures the integrations and may hold an endpoint credential.
  Script 11 reads its column names from the catalogue rather than selecting
  from it.
