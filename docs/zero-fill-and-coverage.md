# Why the forms cannot be zero-filled, and what was built instead

Measured against the live national instance, `hmis.health.go.ug` (DHIS2 41.7),
on 2 September 2026.

## The request

Go over all the reports so that every field gets a value, or a zero where
nothing is reported.

## What the instance says

DHIS2 will not keep the zeros. A dry-run import, which validates exactly as a
real submission would and writes nothing:

```
POST /api/dataValueSets?dryRun=true   element X, value "1"
  -> imported=1 updated=0 ignored=0   conflicts=[]

POST /api/dataValueSets?dryRun=true   element X, value "0"
  -> imported=0 updated=0 ignored=0   conflicts=[]
```

The zero is not rejected. It is not ignored. It raises no conflict. It is
dropped in silence, and the import reports success.

The cause is `zeroIsSignificant`, which is **false on 3,247 of the 3,252 data
elements** across the eight data sets. The five exceptions are all on 105:02-03:
two cold-chain temperature alarms, two refrigerator counts, and male condoms.

Three independent lines of evidence agree:

| Evidence | Reading |
|---|---|
| `zeroIsSignificant` false on 3,247 / 3,252 elements | zeros are not meant to be stored |
| dry-run import of "0" returns `imported=0` | zeros are in fact not stored |
| 2,038 stored values across six data-set/period combinations, **not one a zero** | zeros have never been stored |

On the DHIS2 side, **the absent cell is the zero**. An application that "filled
every field" would report six thousand values submitted where the server had
kept a hundred, and every one of those reports would be wrong.

## What each form actually contains

| Report | Elements | Cells | Cells this compiler answers for |
|---|---|---:|---:|
| 105:01 OPD | 623 | 6,329 | 4,060 |
| 105:02-03 MCH | 432 | 1,433 | — no compiler yet |
| 105:04-05 HTS | 190 | 5,830 | — no compiler yet |
| 105C Palliative | 24 | 240 | — no compiler yet |
| 108 IPD | 849 | 3,906 | ward indicators + Section 6 |
| 033B Surveillance | 239 | 239 | 239 |
| 106a:01-02 HIV | 368 | 7,219 | — no compiler yet |
| 106a:03 TB/Leprosy | 527 | 2,518 | — no compiler yet |

And what is filled today, by anyone, through the existing manual process:

| Report | Period | Stored values | Of cells |
|---|---|---:|---:|
| 105:01 | June 2026 | 643 | 10.2% |
| 105:01 | July 2026 | 112 | 1.8% |
| 108 | July 2026 | 9 | 0.2% |
| 105:04-05 | July 2026 | 223 | 3.8% |
| 106a:01-02 | Q2 2026 | 1,051 | 14.6% |
| 033B | week 30, 2026 | 0 | 0% |

The real gap is not missing zeros. It is that between 85 and 100 per cent of
every form is empty, and that 105:01 fell from 643 values in June to 112 in
July.

## The second reason not to zero everything

A zero is a claim. Printing `0` against *Cholera — Deaths* asserts that we
looked and there were none.

105:01 carries 6,329 cells. This compiler answers for 4,060 of them — attendance
and the diagnosis grid. The remaining 2,269 are nutrition (1,474 cells),
rehabilitation, gender-based violence, cancer and adverse events, and they are
filled by other staff from paper registers. A zero of ours in their column is a
false statement about their work, and had it been pushable it would have
overwritten their entry.

## What was built

**Ownership is derived, not declared.** `api/_lib/coverage.py` computes the set
of cells each compiler answers for from the compiler's own mapping tables, so
extending a mapping extends the zero-fill and the two cannot drift apart.

- **OPD** — the two attendance elements, plus every element on the
  *OPD Age(0-28days+) & Sex* disaggregation. That combination separates the
  diagnosis grid from the rest of 105:01 cleanly: 406 of 623 elements carry it,
  and they are exactly attendance plus the thirty condition groups. Checked
  against the alternative of matching the code prefix in the element name, which
  would have been wrong — `EP` has 25 elements inside the grid and one outside,
  `CA` 8 inside and 19 outside, `TP` 9 and 13.
- **IPD** — the four ward indicators the compiler derives, plus every Section-6
  case and death element in the diagnosis index. `CI01` (beds available) is
  deliberately excluded: it is a facility declaration, and zero beds is not a
  thing to assert.
- **033B** — all 239 elements. This is the report where the zero carries most
  weight, because "no cases of cholera this week" is the substance of a
  surveillance return rather than an absence of data.
- **The other five reports** own nothing, because they have no compiler. Their
  preview shows the blank official form, which is the honest rendering.

**The zero lives in the preview and nowhere else.** Three states are now
distinguishable on the page:

| Appearance | Meaning |
|---|---|
| bold, on a tinted ground | counted from the register |
| plain grey `0` | this compiler answers for the cell and found none |
| blank | not compiled here — entered by other staff from another register |

A compiled zero and an imputed zero print the same character, so the difference
is carried in the data rather than inferred from the value, and a legend on the
page states how many cells belong to other staff.

**Three gates stop an imputed zero reaching DHIS2.** They are never persisted;
the push reads `compiled_data` straight from the database; and `build_payload`
filters on the `imputed` flag regardless, so a future caller who passes the
displayed values by mistake still submits only what was measured.
`scripts/test_coverage.py` holds 32 checks over this, including one that hands
`build_payload` the displayed set and asserts no zero survives.

## What to raise with the Ministry

For 033B specifically, `zeroIsSignificant = false` looks like a configuration
error rather than a decision. A weekly epidemiological surveillance return
distinguishes "no cases of cholera" from "no report submitted", and at present
DHIS2 cannot record the difference. Setting `zeroIsSignificant` on the 033B
elements would let a zero surveillance week be stated rather than inferred from
silence.
