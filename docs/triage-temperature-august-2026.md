# Temperature recording at outpatient triage

**Jinja Regional Referral Hospital · August 2026 · for the triage and quality improvement teams**

## The short version

A fever is a temperature of 37.5 °C or above. That definition is what HMIS 105:01 line
EP01a, *Suspected Malaria (fever)*, is meant to count, and EP01a is the denominator for
every malaria figure the hospital reports.

In August the triage record produced **45** clients at or above 37.5 °C. In the same month
the hospital confirmed **87** malaria cases by blood slide or RDT. A denominator smaller
than the numerator it carries is not a low month; it is a measurement that is not being
taken.

## What the month actually shows

| | August 2026 |
|---|---|
| Outpatient visits | 15,450 |
| Visits with a triage record | 11,179 (72%) |
| Visits with a temperature recorded | **3,535 (23%)** |
| Readings at or above 37.5 °C | 45 |
| Readings at or above 38.0 °C | **9** |

Twenty-three per cent capture is the first problem. Even among clients who reached triage
and had a record made, only about one in three had a temperature entered.

## The readings that were taken

| Reading | Count |
|---|---|
| Below 35.0 °C | 82 |
| 35.0 to 35.9 | 180 |
| **36.0 to 36.9** | **2,830** |
| 37.0 to 37.4 | 398 |
| 37.5 to 37.9 | 36 |
| 38.0 and above | 9 |

Three things stand out, and none of them is clinical.

**Eighty per cent of every reading in the month falls inside a single degree.** Real
outpatient temperatures do not distribute that way. A concentration this tight, with 1,773
readings landing in the half-degree from 36.0 alone, is the signature of a value being
accepted rather than a thermometer being read.

**Nine readings in the whole of August reached 38.0 °C.** A regional referral hospital
seeing more than fifteen thousand outpatients in a month sees a great many more febrile
clients than nine.

**Eighty-two readings sit below 35.0 °C, some as low as 31.0.** A temperature of 31 °C is a
resuscitation emergency, not an outpatient queue. These are entry errors, and they matter
beyond their number: they show the field accepts anything, so nothing downstream can trust
what it holds.

## Why it matters beyond the malaria line

Reported malaria test positivity at this hospital has run at 73 to 82 per cent up to 2022
and then 33 and 27 per cent. Positivity above 70 per cent is not credible for a referral
hospital, and the swing between the two periods looks like a change in how fevers were
counted rather than a change in malaria. EP01a is the figure at the root of it, and it has
never had a countable source. Triage temperature is the obvious candidate and the only one
the system already holds.

Two further consequences follow. Case definitions for the weekly 033B surveillance return
rest on fever as well, so the same gap weakens epidemic detection. And triage exists to
find the sick client in the queue; a vital sign recorded for fewer than one visit in four
is not performing that job either.

## What would close it

1. **Record a temperature for every outpatient triaged.** This is the whole of the fix.
   Twenty-three per cent to something near complete would give EP01a a real denominator
   for the first time.
2. **Reject impossible values at entry.** A range check on the triage screen, refusing
   anything below 30 °C or above 43 °C, removes the 82 obviously wrong readings at source.
3. **Ask ClinicMaster whether the field carries a default.** The concentration at exactly
   36.0 is consistent with a pre-filled value being saved unchanged, which would be a
   configuration matter rather than a training one.
4. **Record fever history as well as the reading.** The Ministry's definition of suspected
   malaria is fever *or history of fever*. A client who took paracetamol before walking in
   is suspected malaria and will not be 37.5 at triage. ClinicMaster has free-text
   presenting-complaint fields, but no coded fever field for general outpatients, so this
   would need a small configuration change to be countable.

Until capture improves, EP01a cannot be compiled from triage and the malaria chain stays
incomplete at its first link.

## Where these figures come from

ClinicMaster, database `ClinicMasterMOH`, outpatient visits between 1 and 31 August 2026.
Read by `scripts/sql/14_opd_rule_measurement.sql`, sections 7 and 8. Aggregates only; no
patient record was read.
