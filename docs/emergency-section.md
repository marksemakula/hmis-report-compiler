# HMIS 105:01 section 1.3.25: Emergency Medical Services from ClinicMaster

This note records how the compiler fills four lines of the 105:01 from the Jinja RRH ClinicMaster database, and why. The code is in `api/_lib/emergency.py`. The generated extraction scripts (the SQL-only, Python and PowerShell versions) carry the rules, and `scripts/test_emergency.py` holds them to the form.

| Line | What the form asks | What the extract counts |
|---|---|---|
| ES01a to d | Emergency cases at the facility: medical, obstetric and gynaecological, surgical, road traffic injuries | Every casualty visit (community ACCIDENT AND EMERGENCY), whether admitted or not, with one category each |
| ES07a, b | Patients with external haemorrhage; of whom controlled | Visible external bleeding in the clinical text; control written down or a dressing, suturing or debridement billed to the visit |
| ES08a to e | Road traffic injuries: motor vehicle, motor cycle, bicycle, pedestrian, other | The road user named in the text, for road traffic cases only |
| ES09a to d | Deaths at the emergency unit, by category | A death registered on the day of arrival or the next, or the visit's admission discharged Deceased in the same window |

All lines are split by the OPD age bands and sex. ES01b and ES09b are written only for women aged 10 and over, because those are the only boxes the form draws.

## Why rules over text, not ClinicMaster's emergency module

ClinicMaster has a full emergency module, but Jinja does not use it: there are 14 registrations and one exit record in the whole database. Everything known about a casualty client sits in the visit, its free text (presenting complaint, provisional diagnosis, triage notes, admission note, first ward round) and what happened afterwards. Coded diagnoses exist for only about a quarter of casualty visits, so codes are used where present and never relied on alone.

## Findings that shaped the rules (measured 2 November 2026, June to October 2026)

- **Where the bed is booked says little about the client.** Until August most casualty admissions were booked onto casualty's own ward, 40440, and many stayed there in the record for days. From September most were booked straight onto destination wards. These included the eye wards (146 in September, against 5 in June to August) and the TB ward (257 in October), which were plainly holding general admissions. Eye-ward beds are therefore no longer read as a surgical signal; beds on the surgical and orthopaedic wards still are.
- **The treating specialty changed in September.** Until August most casualty visits were recorded against GENERAL DOCTOR. From September they were recorded against PHYSICIAN (398 and 570) and SURGEON (307 and 301). The surgical share rose with it, from about a quarter to between a quarter and two fifths. That is better information, not an artefact, but it means months before and after September are not strictly comparable.
- **WardTransfer is not a record of leaving casualty.** Its first row for every admission is the admission's own placement (from and to the same ward), so the first death rule, which required "no transfer", excluded almost every death and found 0 to 3 a month.
- **Deaths are recorded by date only.** Every death register entry since June is at midnight, so "within a day of arrival" means the arrival day and the next.
- **Most road traffic notes do not name the road user.** About 45 per cent of road traffic cases are written as "involved in RTA, sustained..." with no vehicle or role, and fall to ES08e, Other. A word count of those notes found nothing more to recognise.

## Monthly figures from ClinicMaster (measured 2 November 2026)

Lines unaffected by the November corrections, and ES09 under the corrected rule:

| Month | Casualty cases | ES01 obs/gyn | ES01 RTI | ES07a | ES07b | ES08 a / b / c / d / e | ES09 (corrected) | ES09 (first rule) |
|---|---|---|---|---|---|---|---|---|
| June 2026 | 1,044 | 20 | 133 | 46 | 9 | 12 / 44 / 1 / 13 / 63 | 3 | 2 |
| July 2026 | 1,140 | 14 | 155 | 66 | 13 | 7 / 52 / 4 / 19 / 73 | 1 | 0 |
| August 2026 | 1,147 | 8 | 176 | 75 | 22 | 14 / 49 / 7 / 23 / 83 | 5 | 3 |
| September 2026 | 1,050 | 17 | 132 | 42 | 9 | 13 / 34 / 3 / 24 / 58 | 12 | 1 |
| October 2026 | 1,261 | 12 | 153 | 49 | 12 | 14 / 29 / 3 / 34 / 73 | 5 | 0 |

The figures reported in eHMIS, for comparison: June 781 cases, ES07 55 and 51, ES09 23; July 866 cases, ES07 51 and 47, ES09 27.

Surgical and medical cases were 225 and 666 in June, 277 and 694 in July, 254 and 709 in August, 445 and 456 in September, and 344 and 752 in October under the first rule. Dropping eye-ward beds as a surgical signal moves at most 3, 129 and 15 cases from surgical to medical in August, September and October; the exact split is set when October is next run against the database.

## What the extract cannot see

- **ES09 is a minimum.** June and July were reported in eHMIS at 23 and 27 deaths at the unit. The EMR holds 7 and 4 deaths of casualty clients within a week of arrival in those months. The source those reported figures were compiled from should be preferred while the two disagree. A death within a day of arrival on a ward the client had already reached is counted, and so is a registered brought-in-dead; neither can be told apart in the EMR.
- **ES07b is a floor.** Bleeding that was controlled and not written down cannot be seen.
- **ES01 is higher than the reported count** (about 1,050 to 1,260 cases a month against 781 and 866 reported), because the EMR counts every casualty visit, including clients seen and sent on.

The single change that would improve all four lines is using ClinicMaster's own emergency registration and exit forms at casualty. The arrival mode, mechanism of injury, bleeding control and outcome would then be recorded as fields, not inferred from notes.

## Run time

The first version of these rules took 7 min 48 s for October 2026 on its own, and the whole October script about 8 minutes, long enough that Azure Data Studio refused to save results that had not yet finished. On 3 November 2026 the rules were rewritten to find casualty visits by their community code (507BUV), to compute each step once, and to read the notes one at a time as ordinary text. The October emergency figures came out identical, all 72 groups and 1,261 cases, and the whole script now runs in about 34 seconds.
