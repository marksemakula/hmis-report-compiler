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

**Request** — a FHIR transaction bundle. Three top-level keys, present on all
2,000 messages sampled:

| Key | JSON type |
|---|---|
| `resourceType` | string — `"Bundle"` |
| `type` | string — `"transaction"` |
| `entry` | array of objects |

Median payload is 7,988 bytes; the largest seen is 19,713. 103,171 of the
104,137 stored messages are valid JSON.

**Response** — a FHIR transaction-response bundle:

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
Harmless to us — we key on the entry ids — but worth reporting to CPHL, since
it makes their own responses impossible to correlate.

### The empty-entry response

97,908 of the responses have `"entry": []` — accepted, but nothing created.
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
| `INTLabResults` | 28,211 | one row per test |
| `INTLabResultsEXT` | 250,667 | one row per analyte within a test |
| `INTTestCMIntegrationResponse` | 333,895 | raw `payloadmsg` |

`INTLabResults` carries `SpecimenNo`, `TestCode`, `TestDateTime`, `Result`,
`UnitMeasure`, `NormalRange`, `ResultFlagID`, `LabTechnologist` — everything a
laboratory tally on an HMIS form needs, on the same server as the visits.

**Consequence for the compiler.** No network connector is required to fill the
laboratory fields on HMIS 105 and 106a. The on-premise agent reads
`INTLabResults` exactly as it reads `Visits`, aggregates on site, and posts
counts. The private-LAN problem we were bracing for does not arise, because the
data never had to cross a network we could not route to.

A client for `labhie` remains worth building later, for *ordering* tests and for
results that ALIS holds but ClinicMaster has not pulled. It is no longer on the
critical path for reporting.

## Open questions, answered by script 11

1. Which tests exist, and in what volume.
2. What a result looks like — `Positive`, `POS`, `1`, `R` — since a tally of
   positives cannot be written against an unseen vocabulary.
3. How `SpecimenNo` reaches a visit, and therefore an age and a sex. Without
   that join every laboratory cell on the form stays blank regardless of how
   many results we hold.

## For CPHL

Three findings from the Ignition debug page the application served publicly:

- Laravel **6.20.45** — security support ended September 2022.
- PHP **7.4.3** — security support ended November 2022.
- `APP_DEBUG` is **enabled in production**. The exception page exposes the
  environment, including database credentials, to any unauthenticated visitor
  who triggers an error. This is the most urgent of the three.

A request worth making of them: `routes/api.php` and the `LabRequest` form
request class from the private repository. Those two files are the entire
specification we have had to reverse-engineer.

## Handling rules that apply to this work

- `INTLabRequestDetails.JsonMessage` contains patient data — names, numbers,
  dates of birth. Script 10 reads key names only and never values. Any future
  script that touches it must do the same.
- The ALIS account credential supplied in conversation should be rotated. It is
  not stored in this repository and will not be; the connector, when it is
  built, reads it from an environment variable.
- `INTAgents` configures the integrations and may hold an endpoint credential.
  Script 11 reads its column names from the catalogue rather than selecting
  from it.
