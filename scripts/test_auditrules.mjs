/* Checks for the clinical audit rules in app/auditrules.js.
 *
 * The rules are a transcription of three Ministry workbooks' formulas, so the
 * checks are of two kinds: that the transcription says what the workbook
 * says, and that each deliberate departure (CORRECTIONS) behaves as the
 * correction claims. Synthetic clients only - no real line list is read.
 *
 *   node scripts/test_auditrules.mjs
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'app', 'auditrules.js'), 'utf8');
const A = await import(`data:text/javascript;base64,${Buffer.from(src).toString('base64')}`);

const failures = [];
function check(label, got, want) {
  const ok = typeof want === 'function' ? want(got) : JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failures.push(`${label}\n     wanted: ${typeof want === 'function' ? want.toString() : JSON.stringify(want)}\n     got:    ${JSON.stringify(got)}`);
    console.log(`  FAIL  ${label}`);
  } else console.log(`  ok    ${label}`);
}

const REF = '2026-09-29';
const run = (tool, rows, opts = {}) => A.audit(A.TOOLS[tool], rows, { ref: REF, order: 'DMY', ...opts });
const one = (tool, row, opts) => run(tool, [row], opts).records[0];

console.log('\nDates as line lists write them');
check('ISO', A.iso(A.parseDate('2026-01-05')), '2026-01-05');
check('ISO with time, as SQL Server exports it', A.iso(A.parseDate('2022-01-20 00:00:00')), '2022-01-20');
check('DDMMMYY with dashes', A.iso(A.parseDate('12-Jan-22')), '2022-01-12');
check('DD MMM YYYY', A.iso(A.parseDate('3 Sept 2025')), '2025-09-03');
check('day-first slashes', A.iso(A.parseDate('05/01/2026', 'DMY')), '2026-01-05');
check('month-first slashes', A.iso(A.parseDate('05/01/2026', 'MDY')), '2026-05-01');
check('Excel serial', A.iso(A.parseDate(44581)), '2022-01-20');
check('Excel serial as text', A.iso(A.parseDate('44581')), '2022-01-20');
check('EDD as MM/YY', A.iso(A.parseDate('08/26')), '2026-08-01');
check('31 February is not a date', A.parseDate('31/02/2026'), null);
check('free text is not a date', A.parseDate('not done'), null);
check('order settled day-first', A.detectDateOrder([{ d: '25/01/2026' }], ['d']).order, 'DMY');
check('order settled month-first', A.detectDateOrder([{ d: '01/25/2026' }], ['d']).order, 'MDY');
check('ambiguous file defaults to day-first', A.detectDateOrder([{ d: '01/02/2026' }], ['d']).order, 'DMY');
check('DATEDIF months, day not yet reached',
  A.monthsBetween(A.parseDate('2026-01-31'), A.parseDate('2026-03-30')), 1);

console.log('\nFacility status from days past the next appointment');
const st = (d) => A.facilityStatus(A.parseDate(d), A.parseDate(REF));
check('appointment still ahead', st('2026-10-10'), 'Active');
check('on the day', st('2026-09-29'), 'Active');
check('7 days late', st('2026-09-22'), 'Missed Appointment');
check('8 days late', st('2026-09-21'), 'Early IIT');
check('28 days late', st('2026-09-01'), 'Early IIT');
check('29 days late', st('2026-08-31'), 'Late IIT');
check('90 days late', st('2026-07-01'), 'Late IIT');
check('91 days late', st('2026-06-30'), 'Defaulter');

console.log('\nViral load, by category or by number');
check('dropdown suppressed', A.vlClass('<1,000 copies/mL', 1000), 'suppressed');
check('dropdown unsuppressed', A.vlClass('≥1,000 copies/mL', 1000), 'unsuppressed');
check('number below threshold', A.vlClass('845', 1000), 'suppressed');
check('number at threshold', A.vlClass('1,000', 1000), 'unsuppressed');
check('PMTCT threshold 200', A.vlClass('450', 200), 'unsuppressed');
check('target not detected', A.vlClass('Target Not Detected', 1000), 'suppressed');
check('blank', A.vlClass('', 1000), '');

console.log('\nHeaders: the workbooks\' own text maps onto every entry field');
const PMTCT_HEAD = ['Region', 'District ', 'Facility Name ', "Mother's ART/HIV Clinic No.", 'Client catergory(Select from the cell drop down)',
  'If breast feeding, State the EID no of the baby', 'If pregnant record EDD(DDMMMYY)', 'Baby DOB  (DDMMMYY)', 'Delivery outcomes',
  'Current baby age(mths)', 'Age (dependent on column K)', 'Age groups', 'Weight (Kg)', "Mother's Date of birth (DDMMMYY)", 'DSDM approach',
  'Last Encounter Date DDMMMYY', 'Next Appointment date DDMMMYY', 'Facility Status in the review period              ', 'Follow up outcomes',
  'CHW attached to PLHIV (CLF/YAP/PEER):', 'CLF/ YAP phone No:', 'Last Community contact Date with CHW DDMMMYY',
  'Next Community contact date with CHW DDMMMYY', 'MBP address Status at contact             ',
  'No. of biological children/siblings <19 yrs', 'No. of biological children/siblings <19 yrs with a known HIV status',
  'No. of biological children/siblings <19 yrs who are HIV+', 'No. of biological children/siblings <19 yrs on ART',
  'Fill Y if index testing of biological siblings of clients is completed or else it’s a N', 'No. of sexual partners',
  'No. of sexual partners with a known HIV status', 'No. of sexual partners who are HIV+', 'No. of sexual partners on ART',
  'Fill Y if index testing of sexual partners is completed or else it’s a N', 'ART START DATE (DDMMMYY) -Initiation',
  'Current ART Regimen   Line    (Pick from the cell drop down)', 'CURRENT ARV REGIMEN', 'CURRENT ARV start date             DDMMMYY',
  'Current VL result (Copies/ml)', 'Current VL result date                             (DDMMMMYY)', 'VL UPDATED           Y/N/NE',
  'If VL update is N state the new  sample collection date DD/MMM/YY', 'On a DTG-based regimen (Y/N/NE)',
  'No. of IAC sessions held for the Unsuppressed ', 'HIVDRT sampling date DDMMMYY',
  'HIVDRT Result/Switch decision (pick from the cell drop down list)', 'Switched eligibility ', 'Switched to 2nd/3rd line (Y/N)',
  'TPT STATUS                                                        (Pick from the cell drop down list)',
  'TB Screening assessment                                                         (Pick from the cell drop down list)',
  'Cancer assessment                                                      (Pick from the cell drop down list)',
  'MMD (Months of ART refill at last visit)', 'NVP at birth (Y/N)', 'DUE DATE FOR CTX              RED: Overdue',
  'Age of start of CTX(wks)', 'DUE DATE FOR 1ST PCR            RED: Overdue', 'Sample Collection date (dd/mm/yyyy)', 'Age at PCR (weeks)',
  '1st PCR Result', 'Date result was given to care giver (dd/mm/yy)', 'Enhance ART prophylaxis (If baby is bled beyond 6 weeks)',
  'DUE DATE FOR 2ND PCR:  RED: Overdue', 'Sample Collection date (dd/mm/yyyy)', 'Age at PCR (Months)', '9mths PCR Result',
  'Date result given to care giver (dd/mm/yy)', 'Date(dd/mm/yy) when breastfeeding stopped', 'DUE DATE 3RD PCR:  RED: Overdue',
  'Sample Collection date (dd/mm/yyyy)', 'Age at PCR (Months)', 'PCR Result after Breastfeeding', 'Date result given to care giver (dd/mm/yyyy)',
  'DUE DATE FOR RAPID TEST:  RED: Overdue', 'Sampling collection date(dd/mm/yy)', 'Age at rapid test (months)', 'Results (Negative/Positive)',
  'Linkage : ART No. of positive infant ', 'Final outcome', 'MBP <25 yrs enrolled in Group ANC ', 'On family connect', 'OVC Screening',
  'OVC enrolment', 'Index testing of children', 'Comments'];
const pm = A.mapHeaders(A.TOOLS.pmtct, PMTCT_HEAD);
check('PMTCT: every entry field found', pm.missing, []);
const byKey = Object.fromEntries(Object.entries(pm.map).map(([i, k]) => [k, +i]));
check('PMTCT: the three "Sample Collection date" columns land in order',
  [PMTCT_HEAD[byKey.pcr1_date + 1], PMTCT_HEAD[byKey.pcr2_date + 2], PMTCT_HEAD[byKey.pcr3_date + 2]],
  ['Age at PCR (weeks)', '9mths PCR Result', 'PCR Result after Breastfeeding']);
check('PMTCT: computed columns are not mistaken for entry ones',
  pm.unknown.includes('Current baby age(mths)') && pm.unknown.includes('VL UPDATED           Y/N/NE'), true);

const EID_HEAD = ['IP Name', 'District', 'HF Name', 'Data source registers: ANC, MAT,YCC, EID', 'Initial encounter date',
  "Mother's PMTCT code (TRR,TRRK ETC.)", 'Mother ID No.', 'Mother ART no:', 'Facility where mother gets HIV care', 'Sub county', 'KAGE',
  'Village', 'ART START DATE', 'Current VL result', 'Date of current VL result', 'mother risk assessment', 'Is VL updated? Y/N/NE',
  'EDD (MM/YY)', 'DOB (DD/MM/YY)', 'BABY (Alive/Other)', 'CURRENT AGE OF THE BABY (In months)',
  'If Live Baby, state EID No  (e.g. m/y/001).', 'EID care facility NAME', 'Last encounter date', 'Next appt date ',
  'NVP at birth (Y/N)', 'DUE DATE FOR CTX (RED:Due; YELLOW: Due in next 7days', 'Age of start of CTP(wks)', 'DUE DATE FOR  1ST PCR',
  'Sample Collection date (dd/mm/yyyy)', 'Age at PCR (weeks)', '1st PCR Result', 'Date result given to care giver (dd/mm/yy)',
  'Enhance ART prophylaxis (If baby is bled beyond 6 weeks)', 'DUE DATE FOR  2ND PCR', 'Sample Collection date (dd/mm/yyyy)',
  'Age at PCR (Months)', '2ND PCR Result', 'Date result given to care giver (dd/mm/yy)', 'Date(dd/mm/yy) when breastfeeding stopped',
  'DUE DATE 3RD PCR', 'Sample Collection date (dd/mm/yyyy)', 'Age at PCR (Months)', '3ND PCR Result',
  'Date result given to care giver (dd/mm/yyyy)', 'DUE DATE FOR RAPID TEST', 'Sampling collection date(dd/mm/yy)',
  'Age at rapid test (months)', 'Results (N/P)', 'Date result given to care giver (dd/mm/yyyy)', 'Linkage : ART No. of positive infant ',
  'STATUS', 'OVC screening assessment              ', 'If enrolled to OVC/CSO, State  ID number at OVC/CSO',
  'CLF/ YAP attached to MBP:', 'CLF/ YAP phone No:'];
const em = A.mapHeaders(A.TOOLS.eid, EID_HEAD);
check('EID: every entry field found', em.missing, []);
const eKey = Object.fromEntries(Object.entries(em.map).map(([i, k]) => [k, +i]));
check('EID: result-given dates land in order', [eKey.pcr1_given, eKey.pcr2_given, eKey.pcr3_given, eKey.rapid_given], [32, 38, 44, 49]);

const ADULT_HEAD = ['Region', 'District ', 'Facility Name ', '', 'Client catergory(Select from the cell drop down)', 'Sex'];
const am = A.mapHeaders(A.TOOLS.adult, ADULT_HEAD);
check('Adult: the unlabelled client-number column is placed by position', am.missing.includes('art_no'), false);
const aq = Array(44).fill('x'); aq[42] = '';
check('Adult: so is the unlabelled follow-up outcome (AQ)', Object.values(A.mapHeaders(A.TOOLS.adult, aq).map), ['followup_outcome']);
check('Adult: field keys work as headers (EMR extract)', A.mapHeaders(A.TOOLS.adult, ['art_no', 'dob', 'next_appt']).missing.length,
  A.TOOLS.adult.fields.length - 3);

console.log('\nCSV');
const csv = A.parseCSV('﻿a,b,c\r\n1,"two, quoted","say ""hi"""\r\n\r\n4,5,6\n');
check('BOM, quotes, blank lines', csv, [['a', 'b', 'c'], ['1', 'two, quoted', 'say "hi"'], ['4', '5', '6']]);
check('semicolon files', A.parseCSV('a;b\n1;2'), [['a', 'b'], ['1', '2']]);

console.log('\nAdult rules');
const base = {
  art_no: 'X-1', category: 'NA', sex: 'Female', dob: '1990-01-01', art_start: '2020-01-01', regimen: 'TDF-3TC-DTG',
  vl_result: '<1,000 copies/mL', vl_date: '2026-03-01', last_encounter: '2026-08-01', next_appt: '2026-11-01',
  children_n: '2', children_known: '2', partners_n: '0', tpt_status: 'Completed', tb_status: 'No Signs',
  cancer_status: 'Negative', chw: 'A. Peer', address_status: 'At the same address',
};
let r = one('adult', base);
check('a well-served client is owed nothing', r.outstanding, []);
check('she is in care and Active', [r.inCare, r.derived.status], [true, 'Active']);
check('age group 25-54', r.derived.age_group, '25-54');
check('MMD from last to next visit, in 28-day months', r.derived.mmd_months, 3);

r = one('adult', { ...base, vl_date: '2025-06-01' });
check('CORRECTION: a non-PMTCT adult with a 7-month-old VL is up to date', one('adult', { ...base, vl_date: '2026-02-15' }).derived.vl_updated, 'Y');
check('an adult VL over 12 months old is due', [r.derived.vl_updated, r.flags.vl_sampling], ['N', 'Y']);
check('a breastfeeding woman is held to 6 months',
  one('adult', { ...base, category: 'Breastfeeding', vl_date: '2026-02-15' }).derived.vl_updated, 'N');
check('a sample already taken this quarter clears the VL gap',
  one('adult', { ...base, vl_date: '2025-06-01', vl_new_sample_date: '2026-09-01' }).flags.vl_sampling, 'N');
check('under six months on ART is not yet eligible', one('adult', { ...base, art_start: '2026-06-01' }).flags.vl_sampling, 'NE');

check('index testing incomplete', one('adult', { ...base, children_known: '1' }).flags.index_children, 'Y');
check('no partners: not applicable', one('adult', base).flags.index_partners, 'NA');
check('non-DTG, suppressed: transition owed', one('adult', { ...base, regimen: 'TDF-3TC-EFV' }).flags.dtg, 'Y');
check('non-DTG, unsuppressed: not applicable', one('adult', { ...base, regimen: 'TDF-3TC-EFV', vl_result: '≥1,000 copies/mL' }).flags.dtg, 'NA');

const unsup = { ...base, vl_result: '≥1,000 copies/mL' };
check('unsuppressed, never on IAC: IAC owed', one('adult', { ...unsup, iac_status: 'Never initaited IAC' }).flags.iac, 'Y');
check('unsuppressed, on IAC: given', one('adult', { ...unsup, iac_status: 'On 2nd IAC with G-adherence' }).flags.iac, 'N');
check('suppressed: IAC not applicable', one('adult', base).flags.iac, 'NA');
check('repeat VL high, no HIVDR sample: owed', one('adult', { ...unsup, iac_status: 'Repeat VL ≥1,000 copies/mL' }).flags.hivdr, 'Y');
check('resistant, not switched: switch owed', one('adult', { ...unsup, hivdr_result: 'Resistant to the current regimen ', switched: 'N' }).flags.switch, 'Y');
check('resistant, switched: given', one('adult', { ...unsup, hivdr_result: 'Resistant to the current regimen ', switched: 'Y' }).flags.switch, 'N');
check('partial resistance: not eligible to switch', one('adult', { ...unsup, hivdr_result: 'Partial resistance(to some drugs in the current regimen)' }).flags.switch, 'NE');

check('TPT never initiated: owed', one('adult', { ...base, tpt_status: 'Never Initiated' }).flags.tpt, 'Y');
check('on INH: under way', one('adult', { ...base, tpt_status: 'On INH' }).flags.tpt, 'ON');
check('TB not screened: owed', one('adult', { ...base, tb_status: 'Not screened' }).flags.tb_screening, 'Y');
check('TB case untreated: treatment owed', one('adult', { ...base, tb_status: 'TB case and no TB treatment' }).flags.tb_treatment, 'Y');
check('men are not eligible for cervical screening', one('adult', { ...base, sex: 'Male', cancer_status: '' }).flags.cancer_screening, 'NE');
check('a woman over 55 already screened keeps her result', one('adult', { ...base, dob: '1960-01-01', cancer_status: 'Negative' }).flags.cancer_screening, 'N');
check('women over 55 are not eligible', one('adult', { ...base, dob: '1960-01-01', cancer_status: '' }).flags.cancer_screening, 'NE');
check('"Never screened" is not read as NE', one('adult', { ...base, cancer_status: 'Never screened' }).flags.cancer_screening, (v) => v !== 'NE');
check('a woman of 36 never screened is owed screening', one('adult', { ...base, cancer_status: 'Never screened' }).flags.cancer_screening, 'Y');
check('CORRECTION: positive and untreated is owed treatment', one('adult', { ...base, cancer_status: 'Positive and no treatment' }).flags.cancer_treatment, 'Y');
check('positive and on treatment is given', one('adult', { ...base, cancer_status: 'Positive and on treatment' }).flags.cancer_treatment, 'N');
check('three-month refill counts as MMD even when unsuppressed', one('adult', { ...base, vl_result: '≥1,000 copies/mL' }).flags.mmd, 'N');
check('one-month refill, unsuppressed: MMD not applicable', one('adult', { ...base, vl_result: '≥1,000 copies/mL', next_appt: '2026-10-01', last_encounter: '2026-09-03' }).flags.mmd, 'NE');
check('one-month refill for a suppressed client: MMD owed', one('adult', { ...base, next_appt: '2026-10-01', last_encounter: '2026-09-03' }).flags.mmd, 'Y');

const late = { ...base, next_appt: '2026-08-01', last_encounter: '2026-05-01' };
check('late IIT with no outcome: follow-up owed', one('adult', late).flags.follow_up, 'Y');
check('late IIT is not in care', one('adult', late).inCare, false);
check('active client: follow-up not applicable', one('adult', base).flags.follow_up, 'NE');
check('in care with no CHW: attachment owed', one('adult', { ...base, chw: '' }).flags.chw, 'Y');
check('CORRECTION: a partner found positive and not on ART is owed initiation',
  one('adult', { ...base, partners_n: '1', partners_known: '1', partners_pos: '1', partners_on_art: '0' }).flags.art_linkage, 'Y');
check('every positive on ART: given',
  one('adult', { ...base, children_pos: '1', children_on_art: '1' }).flags.art_linkage, 'N');
check('CORRECTION: a 19-year-old is flagged <20, not 20-24', one('adult', { ...base, dob: '2007-06-01' }).derived.age_group, '<20');

console.log('\nPMTCT rules');
const mbp = {
  art_no: 'M-1', category: 'PMTCT(Breastfeeding)', baby_eid_no: '1/26/001', baby_dob: '2026-06-01', dob: '1998-05-05',
  art_start: '2024-01-01', regimen: 'TDF-3TC-DTG', vl_result: '<200 copies/mL', vl_date: '2026-08-01',
  last_encounter: '2026-09-01', next_appt: '2026-10-01', nvp: 'Completed NVP', ctx_age_wks: '6',
  pcr1_date: '2026-07-13', pcr1_result: 'Negative', pcr1_given: '2026-08-01', chw: 'Peer', children_n: '0', partners_n: '0',
  tpt_status: 'Completed', tb_status: 'No Signs', cancer_status: 'Negative', ganc: 'NE', family_connect: 'Y',
  ovc_screening: 'Not eligible for enrolment', address_status: 'At the same address',
};
r = one('pmtct', mbp);
check('the baby is about four months old', r.derived.baby_age_months, 4);
check('first PCR due at six weeks', A.iso(r.derived.pcr1_due), '2026-07-13');
check('a well-served pair is owed nothing', r.outstanding, []);
check('the 9-month PCR is not yet due', r.flags.pcr2, 'NE');
check('PMTCT VL window is 3 months', one('pmtct', { ...mbp, vl_date: '2026-05-01' }).derived.vl_updated, 'N');
check('PMTCT threshold: 450 copies is unsuppressed, so IAC applies',
  one('pmtct', { ...mbp, vl_result: '450', iac_status: '' }).flags.iac, 'Y');
check('baby under 6 months: MMD not applicable', r.flags.mmd, 'NE');
check('CORRECTION: pregnant woman is not owed NVP', one('pmtct', { ...mbp, category: 'PMTCT(pregnant)', nvp: '' }).flags.nvp, 'NE');
check('breastfeeding, NVP never initiated: owed', one('pmtct', { ...mbp, nvp: 'Never initiated' }).flags.nvp, 'Y');
check('on NVP: under way', one('pmtct', { ...mbp, nvp: 'On NVP' }).flags.nvp, 'ON');
check('first PCR past due and not taken: owed', one('pmtct', { ...mbp, pcr1_date: '', pcr1_result: '', pcr1_given: '' }).flags.pcr1, 'Y');
check('sample taken, result awaited: under way', one('pmtct', { ...mbp, pcr1_result: '', pcr1_given: '' }).flags.pcr1_results, 'ON');
check('result back, not given: owed', one('pmtct', { ...mbp, pcr1_given: '' }).flags.pcr1_results, 'Y');
check('CORRECTION: positive baby with no ART number is owed linkage',
  one('pmtct', { ...mbp, pcr1_result: 'Positive', final_outcome: 'Positive linked to ART' }).flags.infant_linkage, 'Y');
check('CORRECTION: eligible, not enrolled on OVC: owed', one('pmtct', { ...mbp, ovc_screening: 'Eligible but not enrolled' }).flags.ovc_enrolment, 'Y');
check('mother of 28: Group ANC not applicable', r.flags.ganc, 'NE');
check('mother of 22 not in GANC: owed', one('pmtct', { ...mbp, dob: '2004-01-01', ganc: 'N' }).flags.ganc, 'Y');
check('CORRECTION: every mother 25-54 is eligible for screening', one('pmtct', { ...mbp, cancer_status: '' }).flags.cancer_screening, 'Y');

console.log('\nEID rules');
const hei = {
  baby_eid_no: '1/26/002', mother_id: 'M-9', pmtct_code: 'TRRK', art_no: '10', baby_dob: '2026-03-01', baby_status: 'Alive',
  last_encounter: '2026-09-01', next_appt: '2026-10-15', nvp: 'Given for 0 to 6wks', ctx_age_wks: '6',
  pcr1_date: '2026-04-12', pcr1_result: 'Negative', pcr1_given: '2026-05-10', status: 'Active',
  ovc_screening: 'Not eligible', vl_updated: 'Y',
};
r = one('eid', hei);
check('an infant on schedule is owed nothing', r.outstanding, []);
check('CORRECTION: NVP "Not given" is owed', one('eid', { ...hei, nvp: 'Not given' }).flags.nvp, 'Y');
check('NVP given is not a gap', r.flags.nvp, 'N');
check('9-month PCR due and not taken',
  one('eid', { ...hei, baby_dob: '2025-12-01', pcr1_date: '2026-01-12' }).flags.pcr2, 'Y');
check('no EDD and no delivery recorded: ANC follow-up owed', one('eid', { ...hei, baby_dob: '', edd: '' }).flags.anc_followup, 'Y');
check('EDD ahead: not yet', one('eid', { ...hei, baby_dob: '', edd: '12/26' }).flags.anc_followup, 'N');
check('TRR mother with no ART number: enrol mother', one('eid', { ...hei, pmtct_code: 'TRR', art_no: '' }).flags.mother_art, 'Y');
check('CORRECTION: enrolled on OVC with an ID is not a gap', one('eid', { ...hei, ovc_screening: 'Enrolled', ovc_id: 'OVC-1' }).flags.ovc_enrolment, 'N');
check('enrolled on OVC with no ID is a gap', one('eid', { ...hei, ovc_screening: 'Enrolled', ovc_id: '' }).flags.ovc_enrolment, 'Y');
check('an unreturned result is owed to the caregiver', one('eid', { ...hei, pcr1_given: '' }).flags.results_given, 'Y');
check('EID in-care status is the recorded one', one('eid', { ...hei, status: 'LTFU' }).inCare, false);

console.log('\nSummaries and exports');
const res = run('adult', [base, { ...base, art_no: 'X-2', chw: '' }, late, { ...base, art_no: 'X-4', next_appt: '' }]);
const coh = Object.fromEntries(res.summary.cohort.map((c) => [c.label.trim(), c.n]));
check('four on the list', coh['Clients on the line list'], 4);
check('two in care', res.summary.inCare, 2);
check('one late IIT', coh['Late interruption (29-90 days)'], 1);
check('one with no appointment', coh['No next appointment date recorded'], 1);
check('one in care owed nothing', coh['In care and owed no service'], 1);
const chwCascade = res.summary.cascades.find((c) => c.key === 'chw');
check('CHW cascade: 2 eligible, 1 given, 50%', [chwCascade.eligible, chwCascade.given, chwCascade.coverage], [2, 1, 50]);
const list = A.parseCSV(A.exportLineList(A.TOOLS.adult, res));
check('line list: a header and four rows', list.length, 5);
check('line list: the workbook\'s headers come first', list[0].slice(0, 3), ['Region', 'District', 'Facility Name']);
const wl = A.parseCSV(A.exportWorklist(A.TOOLS.adult, res));
check('worklist: only the in-care client with a gap', wl.length, 2);
check('worklist names the service', wl[1][7], (s) => s.includes('Attachment to a CHW'));
const eidRes = run('eid', [hei, { ...hei, baby_eid_no: '1/26/3', nvp: 'Not given', baby_dob: '2026-08-15', pcr1_date: '', pcr1_result: '', pcr1_given: '', ctx_age_wks: '' }]);
const nvpRow = eidRes.summary.eid.find((x) => x.label.includes('NVP'));
check('EID: NVP coverage among infants 0-2 months counts "Given"', [nvpRow.num, nvpRow.den], [0, 1]);
check('every tool lists its corrections', A.TOOL_ORDER.every((k) => A.CORRECTIONS[k].length > 0), true);
check('templates carry the entry headers', A.parseCSV(A.templateCSV(A.TOOLS.eid))[0].length, A.TOOLS.eid.fields.length);

console.log(failures.length ? `\n${failures.length} FAILED\n\n${failures.join('\n\n')}` : '\nAll audit-rule checks passed.');
process.exit(failures.length ? 1 : 0);
