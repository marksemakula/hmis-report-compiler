/* Clinical audit rules - Adult ART, PMTCT (mother-baby pair) and EID.
 *
 * The Ministry's three audit workbooks (implementing-partner line lists, 2022
 * revision) keep their logic in cell formulas: a hidden BackEnd sheet derives
 * ages, viral-load currency and facility status, and a block of "service"
 * columns at the right of each line list marks, per client, whether a service
 * is still owed. This module is those formulas, transcribed once, so that a
 * line list can be audited in the browser without the 30-70 MB workbook and
 * without any patient row leaving the machine.
 *
 * The workbooks' own convention is kept for every service code:
 *
 *   Y   the client is eligible and the service is OUTSTANDING (a gap)
 *   N   the client is eligible and the service has been given
 *   ON  the service is under way (on TPT, on TB treatment, NVP in progress,
 *       a PCR result awaited from the laboratory)
 *   NE  not eligible
 *   NA  not applicable (no partner, no child, not on a failing regimen)
 *
 * so "Y" always means "act on this client", which is what the worklist reads.
 *
 * Where a formula in the workbook is plainly broken, the intended rule is
 * implemented instead and the change is listed in CORRECTIONS, which the page
 * shows beside the results. Nothing is corrected silently.
 *
 * The module is plain JavaScript with no imports so that it runs unchanged in
 * the page and under `node scripts/test_auditrules.mjs`.
 */

export const CODES = {
  Y: 'Outstanding',
  N: 'Given',
  ON: 'Under way',
  NE: 'Not eligible',
  NA: 'Not applicable',
};

/* ------------------------------------------------------------------ values */

const DAY = 86400000;
const MONTHS = {
  jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, sept: 8, oct: 9, nov: 10, dec: 11,
};

export const blank = (v) => v === null || v === undefined || String(v).trim() === '';
const txt = (v) => (blank(v) ? '' : String(v).trim());
const norm = (v) => txt(v).toLowerCase().replace(/\s+/g, ' ');
const is = (v, ...opts) => opts.some((o) => norm(v) === norm(o));

export function num(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const s = txt(v).replace(/,/g, '');
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

const utc = (y, m, d) => {
  const dt = new Date(Date.UTC(y, m, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m && dt.getUTCDate() === d ? dt : null;
};
const fullYear = (y) => (y < 100 ? (y >= 70 ? 1900 + y : 2000 + y) : y);

/**
 * Read a date as a clinic line list writes one.
 *
 * The workbooks ask for DDMMMYY in their headers and mm/dd/yyyy in their
 * ReadMe, and a CSV saved from Excel carries whatever the entering machine's
 * locale produced. So: ISO dates, Excel serial numbers, 12-Jan-22 style,
 * month/year (the EID sheet's EDD), and slashed dates in the order the caller
 * says (see detectDateOrder).
 */
export function parseDate(v, order = 'DMY') {
  if (v instanceof Date) {
    return Number.isNaN(v.getTime()) ? null : utc(v.getUTCFullYear(), v.getUTCMonth(), v.getUTCDate());
  }
  if (typeof v === 'number') {
    if (v > 20000 && v < 80000) return new Date(Date.UTC(1899, 11, 30) + Math.round(v) * DAY);
    return null;
  }
  const s = txt(v);
  if (!s) return null;
  let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$/);
  if (m) return utc(+m[1], +m[2] - 1, +m[3]);
  m = s.match(/^(\d{1,2})[\s\-/.]*([A-Za-z]{3,9})[\s\-/.,]*(\d{2,4})$/);
  if (m) {
    const w = m[2].toLowerCase();
    const mon = MONTHS[w.startsWith('sept') ? 'sept' : w.slice(0, 3)];
    if (mon !== undefined) return utc(fullYear(+m[3]), mon, +m[1]);
  }
  m = s.match(/^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})(?:\s.*)?$/);
  if (m) {
    const [a, b, y] = [+m[1], +m[2], fullYear(+m[3])];
    return order === 'MDY' ? utc(y, a - 1, b) : utc(y, b - 1, a);
  }
  m = s.match(/^(\d{1,2})[/\-.](\d{2}|\d{4})$/);
  if (m && +m[1] >= 1 && +m[1] <= 12) return utc(fullYear(+m[2]), +m[1] - 1, 1);
  if (/^\d{5}(\.\d+)?$/.test(s)) return parseDate(Number(s));
  return null;
}

/** Decide whether slashed dates in a file are day-first or month-first. A
 *  first part over 12 settles it one way, a second part over 12 the other;
 *  a file with neither is ambiguous and falls back to day-first, which is
 *  what Uganda writes. Returns { order, evidence }. */
export function detectDateOrder(rows, keys) {
  let dmy = 0;
  let mdy = 0;
  for (const r of rows) {
    for (const k of keys) {
      const m = txt(r[k]).match(/^(\d{1,2})[/\-.](\d{1,2})[/\-.]\d{2,4}/);
      if (!m) continue;
      if (+m[1] > 12) dmy += 1;
      if (+m[2] > 12) mdy += 1;
    }
  }
  if (mdy > dmy) return { order: 'MDY', evidence: `${mdy} dates only read month-first` };
  if (dmy > 0) return { order: 'DMY', evidence: `${dmy} dates only read day-first` };
  return { order: 'DMY', evidence: 'no date settles it, so day-first is assumed' };
}

const daysBetween = (a, b) => (a && b ? Math.round((b - a) / DAY) : null);
/** Excel's DATEDIF(a, b, "M"): whole months completed. */
export function monthsBetween(a, b) {
  if (!a || !b || b < a) return null;
  let m = (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + (b.getUTCMonth() - a.getUTCMonth());
  if (b.getUTCDate() < a.getUTCDate()) m -= 1;
  return m;
}
const addDays = (d, n) => (d ? new Date(d.getTime() + n * DAY) : null);
export const iso = (d) => (d ? d.toISOString().slice(0, 10) : '');

/**
 * Viral load as suppressed / unsuppressed. The line lists hold either the
 * dropdown category ("<1,000 copies/mL") or, from an EMR extract, a number or
 * a laboratory phrase such as "Target Not Detected".
 */
export function vlClass(v, threshold) {
  const s = norm(v);
  if (!s) return '';
  if (/not detected|undetect|\btnd\b|\bldl\b|below detect/.test(s)) return 'suppressed';
  if (s.startsWith('<')) return 'suppressed';
  if (s.startsWith('≥') || s.startsWith('>')) return 'unsuppressed';
  const n = num(s.replace(/copies.*$/, '').replace(/[^\d.]/g, ''));
  if (n === null) return '';
  return n >= threshold ? 'unsuppressed' : 'suppressed';
}

/** The workbooks' facility status, from days past the next appointment. */
export function facilityStatus(nextAppt, ref) {
  if (!nextAppt) return '';
  const late = daysBetween(nextAppt, ref);
  if (late > 90) return 'Defaulter';
  if (late > 28) return 'Late IIT';
  if (late > 7) return 'Early IIT';
  if (late > 0) return 'Missed Appointment';
  return 'Active';
}
const IN_CARE = ['Active', 'Missed Appointment', 'Early IIT'];
const LOST = ['Early IIT', 'Late IIT', 'Missed Appointment', 'Defaulter'];

/** Index testing complete? Y / N / NA - the BackEnd E and F columns. */
function indexDone(total, known) {
  if (blank(total)) return 'N';
  const t = num(total);
  if (t === 0) return 'NA';
  return t !== null && t === num(known) ? 'Y' : 'N';
}
const gapFrom = (done) => (done === 'Y' ? 'N' : done === 'N' ? 'Y' : 'NA');

/** New positives found through index testing, and whether each is on ART. */
function linkage(r) {
  const pos = (num(r.children_pos) || 0) + (num(r.partners_pos) || 0);
  if (!pos) return 'NE';
  const onArt = (num(r.children_on_art) || 0) + (num(r.partners_on_art) || 0);
  return onArt >= pos ? 'N' : 'Y';
}

const isDTG = (reg) => /dtg/i.test(txt(reg));
const pregnantOrBf = (cat) => /preg|breast|lactat/i.test(txt(cat)) && !/not breast/i.test(txt(cat));
const breastfeeding = (cat) => /breast|lactat/i.test(txt(cat)) && !/not breast/i.test(txt(cat));
const pregnant = (cat) => /preg/i.test(txt(cat));

/* ---------------------------------------------------- shared rule families */

function hivServices({ vlThreshold, key }) {
  const unsup = (r) => vlClass(r.vl_result, vlThreshold) === 'unsuppressed';
  return [
    { key: 'index_children', label: 'Index testing of children', eval: (r, d) => gapFrom(d.index_children_done) },
    { key: 'index_partners', label: 'Index testing of sexual partners', eval: (r, d) => gapFrom(d.index_partners_done) },
    {
      key: 'vl_sampling',
      label: 'Viral load sampling',
      eval: (r, d, ref) => {
        if (d.vl_updated === 'NE') return 'NE';
        if (d.vl_updated === 'Y') return 'N';
        const s = parseDate(r.vl_new_sample_date, d._order);
        if (!s) return 'Y';
        return Math.abs(daysBetween(s, ref)) / 28 < 3 ? 'N' : 'Y';
      },
    },
    {
      key: 'dtg',
      label: 'DTG transition',
      eval: (r, d) => ({ Y: 'N', N: 'Y', NA: 'NA', NE: 'NE' }[d.on_dtg] || 'NE'),
    },
    {
      key: 'iac',
      label: 'IAC initiation',
      eval: (r, d) => {
        if (d.vl_updated === 'NE' || !unsup(r)) return 'NA';
        return blank(r.iac_status) || /never/i.test(txt(r.iac_status)) ? 'Y' : 'N';
      },
    },
    {
      key: 'hivdr',
      label: 'HIVDR sample',
      eval: (r) => {
        if (!/repeat vl/i.test(txt(r.iac_status))) return 'NE';
        return blank(r.hivdr_date) ? 'Y' : 'N';
      },
    },
    {
      key: 'switch',
      label: 'Switch to 2nd/3rd line',
      eval: (r, d) => {
        if (d.switch_eligibility !== 'Eligible') return 'NE';
        return is(r.switched, 'Y', 'Yes') ? 'N' : 'Y';
      },
    },
    {
      key: 'tpt',
      label: 'TPT initiation',
      eval: (r) => {
        const t = r.tpt_status;
        if (is(t, 'Completed', 'On anti TB drugs')) return 'N';
        if (/^on (inh|3hp|1hp|tpt)/i.test(txt(t))) return 'ON';
        if (is(t, 'Not Eligible')) return 'NE';
        return 'Y';
      },
    },
    {
      key: 'tb_screening',
      label: 'TB screening',
      eval: (r) => (blank(r.tb_status) || is(r.tb_status, 'Not screened') ? 'Y' : 'N'),
    },
    {
      key: 'tb_treatment',
      label: 'TB treatment',
      eval: (r) => {
        if (is(r.tb_status, 'On TB treatment')) return 'ON';
        if (is(r.tb_status, 'TB treatment Completed')) return 'N';
        if (is(r.tb_status, 'TB case and no TB treatment')) return 'Y';
        return 'NE';
      },
    },
    {
      key: 'cancer_screening',
      label: 'Cervical cancer screening',
      eval: (r, d) => {
        if (/^ne\b/i.test(txt(r.cancer_status))) return 'NE';
        if (blank(r.cancer_status) || is(r.cancer_status, 'Never screened')) {
          // Age and sex decide eligibility only for a woman not yet screened;
          // a recorded screen stands whatever her age.
          return d.cancer_eligible === false ? 'NE' : 'Y';
        }
        return 'N';
      },
    },
    {
      key: 'cancer_treatment',
      label: 'Cancer treatment',
      eval: (r) => (is(r.cancer_status, 'Positive and no treatment') ? 'Y'
        : is(r.cancer_status, 'Positive and on treatment') ? 'N' : 'NE'),
    },
    {
      key: 'mmd',
      label: 'Multi-month dispensing',
      eval: (r, d) => {
        if (key === 'pmtct' && (pregnant(r.category) || (d.baby_age_months !== null && d.baby_age_months < 6))) return 'NE';
        // The workbook's order: three months or more is given, whatever the
        // VL; under three is a gap only for a suppressed client, since an
        // unsuppressed one (or one with no result) should be seen monthly.
        if (d.mmd_months !== null && d.mmd_months >= 3) return 'N';
        if (d.mmd_months === null) return 'Y';
        return vlClass(r.vl_result, vlThreshold) === 'suppressed' ? 'Y' : 'NE';
      },
    },
    {
      key: 'follow_up',
      label: 'Follow-up of missed clients',
      eval: (r, d) => {
        if (LOST.includes(d.status)) return blank(r.followup_outcome) ? 'Y' : 'N';
        return 'NE';
      },
    },
    {
      key: 'chw',
      label: 'Attachment to a CHW',
      eval: (r, d) => (!IN_CARE.includes(d.status) ? 'NE' : blank(r.chw) ? 'Y' : 'N'),
    },
  ];
}

function hivDerive(r, ref, order, { vlThreshold, pmtct }) {
  const dob = parseDate(r.dob, order);
  const age = dob ? (ref - dob) / DAY / 365.25 : null;
  const ageGroup = age === null ? '' : age >= 55 ? '55+' : age >= 25 ? '25-54' : age >= 20 ? '20-24' : '<20';
  const artStart = parseDate(r.art_start, order);
  const vlDate = parseDate(r.vl_date, order);
  const monthsOnArt = monthsBetween(artStart, ref);
  const vlMonths = monthsBetween(vlDate, ref);

  /* VL currency. The adult workbook tests the category column for
     "Adult client", a value its own dropdown never offers, so every
     non-PMTCT adult on ART six months or more was marked not up to date.
     The rule it meant: pregnant and breastfeeding women every 6 months
     (every 3 in the PMTCT tool), everyone else every 12. */
  let vlUpdated;
  if (monthsOnArt === null) {
    vlUpdated = 'N';
  } else if (pmtct) {
    vlUpdated = monthsOnArt < 3 ? 'NE' : vlMonths !== null && vlMonths <= 3 ? 'Y' : 'N';
  } else if (monthsOnArt < 6) {
    vlUpdated = 'NE';
  } else {
    const window = pregnantOrBf(r.category) ? 5 : 11;
    vlUpdated = vlMonths !== null && vlMonths <= window ? 'Y' : 'N';
  }

  const unsup = vlClass(r.vl_result, vlThreshold) === 'unsuppressed';
  const onDtg = blank(r.regimen) ? 'NE'
    : isDTG(r.regimen) ? 'Y' : unsup ? 'NA' : breastfeeding(r.category) ? 'NE' : 'N';

  const hivdr = txt(r.hivdr_result);
  const switchEligibility = !hivdr ? '' : /not resistant|partial/i.test(hivdr) ? 'Not eligible' : 'Eligible';

  const last = parseDate(r.last_encounter, order);
  const next = parseDate(r.next_appt, order);
  const mmd = last && next ? Math.round(daysBetween(last, next) / 28) : null;

  /* Cervical screening: women 25-54. The PMTCT BackEnd reads sex from a
     column that no longer exists (#REF!); every client there is a mother. */
  const sex = pmtct ? 'Female' : txt(r.sex);
  const cancerEligible = /^m/i.test(sex) ? false : ageGroup === '' ? null : ageGroup === '25-54';

  return {
    age: age === null ? null : Math.round(age * 10) / 10,
    age_group: ageGroup,
    index_children_done: indexDone(r.children_n, r.children_known),
    index_partners_done: indexDone(r.partners_n, r.partners_known),
    months_on_art: monthsOnArt,
    vl_updated: vlUpdated,
    on_dtg: onDtg,
    switch_eligibility: switchEligibility,
    mmd_months: mmd,
    status: facilityStatus(next, ref),
    cancer_eligible: cancerEligible,
    without_dob: dob ? 0 : 1,
    _order: order,
  };
}

/** Infant testing milestones shared by PMTCT and EID. A sample is Y once it
 *  falls due and nothing is recorded, N once recorded, NE before it falls due.
 *  A result hand-over is ON while the result is awaited from the laboratory. */
function milestones() {
  const sampled = (key, label, dueKey, dateKey) => ({
    key,
    label,
    eval: (r, d, ref) => {
      const when = d[dueKey];
      if (!when || when > ref) return 'NE';
      return blank(r[dateKey]) ? 'Y' : 'N';
    },
  });
  const given = (key, label, dateKey, resultKey, givenKey) => ({
    key,
    label,
    eval: (r) => {
      if (blank(r[dateKey])) return 'NE';
      if (blank(r[resultKey])) return 'ON';
      return blank(r[givenKey]) ? 'Y' : 'N';
    },
  });
  return [
    {
      key: 'ctx',
      label: 'Start CTX (6 weeks)',
      eval: (r, d, ref) => (!d.ctx_due || d.ctx_due > ref ? 'NE' : blank(r.ctx_age_wks) ? 'Y' : 'N'),
    },
    sampled('pcr1', '1st PCR sample (6 weeks)', 'pcr1_due', 'pcr1_date'),
    given('pcr1_results', '1st PCR result to caregiver', 'pcr1_date', 'pcr1_result', 'pcr1_given'),
    sampled('pcr2', '2nd PCR sample (9 months)', 'pcr2_due', 'pcr2_date'),
    given('pcr2_results', '2nd PCR result to caregiver', 'pcr2_date', 'pcr2_result', 'pcr2_given'),
    sampled('pcr3', 'PCR 6 weeks after breastfeeding stops', 'pcr3_due', 'pcr3_date'),
    given('pcr3_results', 'Post-breastfeeding PCR result to caregiver', 'pcr3_date', 'pcr3_result', 'pcr3_given'),
    sampled('rapid', 'Rapid test (18 months)', 'rapid_due', 'rapid_date'),
  ];
}

/** Infant schedule. National EID guidance: CTX and the first DNA PCR at six
 *  weeks, the second PCR at nine months, a third six weeks after
 *  breastfeeding stops, the rapid test at eighteen months. */
function infantDerive(r, ref, order, excludePregnant) {
  const bdob = parseDate(r.baby_dob, order);
  const none = excludePregnant && pregnant(r.category);
  return {
    baby_age_months: none || !bdob ? null : Math.round(((ref - bdob) / DAY / 30) * 10) / 10,
    ctx_due: none ? null : addDays(bdob, 42),
    pcr1_due: none ? null : addDays(bdob, 42),
    pcr2_due: none ? null : addDays(bdob, 9 * 28),
    pcr3_due: none ? null : addDays(parseDate(r.bf_stopped, order), 42),
    rapid_due: none ? null : addDays(bdob, 18 * 28),
  };
}

/* ------------------------------------------------------------------- tools */

const F = (key, header, type = 'text', extra = {}) => ({ key, header, type, ...extra });

const HIV_CORE = [
  F('children_n', 'No. of biological children/siblings <19 yrs', 'number'),
  F('children_known', 'No. of biological children/siblings <19 yrs with a known HIV status', 'number'),
  F('children_pos', 'No. of biological children/siblings <19 yrs who are HIV+', 'number'),
  F('children_on_art', 'No. of biological children/siblings <19 yrs on ART', 'number'),
  F('partners_n', 'No. of sexual partners', 'number'),
  F('partners_known', 'No. of sexual partners with a known HIV status', 'number'),
  F('partners_pos', 'No. of sexual partners who are HIV+', 'number'),
  F('partners_on_art', 'No. of sexual partners on ART', 'number'),
  F('art_start', 'ART START DATE (DDMMMYY) -Initiation', 'date'),
  F('regimen_line', 'Current ART Regimen Line (Pick from the cell drop down)'),
  F('regimen', 'CURRENT ARV REGIMEN'),
  F('regimen_start', 'CURRENT ARV start date DDMMMYY', 'date'),
  F('vl_result', 'Current VL result (Copies/ml)'),
  F('vl_date', 'Current VL result date (DDMMMMYY)', 'date'),
  F('vl_new_sample_date', 'If VL update is N state the new sample collection date DD/MMM/YY', 'date'),
  F('iac_status', 'No. of IAC sessions held for the Unsuppressed'),
  F('hivdr_date', 'HIVDRT sampling date DDMMMYY', 'date'),
  F('hivdr_result', 'HIVDRT Result/Switch decision (pick from the cell drop down list)'),
  F('switched', 'Switched to 2nd/3rd line (Y/N)'),
  F('tpt_status', 'TPT STATUS (Pick from the cell drop down list)'),
  F('tb_status', 'TB Screening assessment (Pick from the cell drop down list)'),
  F('cancer_status', 'Cancer assessment (Pick from the cell drop down list)'),
];

const ADULT = {
  key: 'adult',
  label: 'Adult ART audit',
  short: 'Adult ART',
  population: 'People living with HIV aged 20 years and over, one row per client on the ART register.',
  workbook: 'ADULT AUDIT TOOL REVISED.xlsx',
  sheet: 'Adult audit tool',
  idField: 'art_no',
  vlThreshold: 1000,
  /* Two columns in the adult sheet carry no header text at all: the client
     number (D) and the follow-up outcome (AQ). A CSV saved from the sheet
     arrives with those cells empty, so they are placed by position. */
  blankHeaders: { 3: 'art_no', 42: 'followup_outcome' },
  fields: [
    F('region', 'Region'),
    F('district', 'District'),
    F('facility', 'Facility Name'),
    F('art_no', 'ART/HIV Clinic No.', 'text', { aliases: ['ART No', 'ART number', 'HIV Clinic No', 'Clinic No'] }),
    F('category', 'Client catergory(Select from the cell drop down)', 'text', { aliases: ['Client category'] }),
    F('sex', 'Sex'),
    F('weight', 'Weight (Kg)', 'number'),
    F('dob', 'Date of birth (DDMMMYY)', 'date'),
    ...HIV_CORE,
    F('dsdm', 'DSDM approach'),
    F('last_encounter', 'Last Encounter Date DDMMMYY', 'date'),
    F('next_appt', 'Next Appointment date DDMMMYY', 'date'),
    F('followup_outcome', 'Follow up outcomes'),
    F('chw', 'CHW attached to PLHIV (CLF/YAP/PEER):'),
    F('chw_phone', 'CLF/ YAP phone No:'),
    F('chw_last_contact', 'Last Contact Date with CHW DDMMMYY', 'date'),
    F('chw_next_contact', 'Next Contact date with CHW DDMMMYY', 'date'),
    F('address_status', 'Address Status at contact'),
    F('comments', 'Comments'),
  ],
  derive: (r, ref, order) => hivDerive(r, ref, order, { vlThreshold: 1000, pmtct: false }),
  services: [
    ...hivServices({ vlThreshold: 1000, key: 'adult' }),
    { key: 'art_linkage', label: 'ART initiation of new positives', eval: (r) => linkage(r) },
    { key: 'address', label: 'Address confirmed at contact', eval: (r) => (blank(r.address_status) ? 'Y' : 'N') },
  ],
};

const PMTCT = {
  key: 'pmtct',
  label: 'PMTCT mother-baby pair audit',
  short: 'PMTCT',
  population: 'HIV-positive pregnant and breastfeeding women and their exposed infants at the mother-baby care point.',
  workbook: 'PMTCT audit tool.xlsx',
  sheet: 'PMTCT audit tool',
  idField: 'art_no',
  vlThreshold: 200,
  fields: [
    F('region', 'Region'),
    F('district', 'District'),
    F('facility', 'Facility Name'),
    F('art_no', "Mother's ART/HIV Clinic No.", 'text', { aliases: ['ART No', 'Mother ART No'] }),
    F('category', 'Client catergory(Select from the cell drop down)', 'text', { aliases: ['Client category'] }),
    F('baby_eid_no', 'If breast feeding, State the EID no of the baby', 'text', { aliases: ['EID No'] }),
    F('edd', 'If pregnant record EDD(DDMMMYY)', 'date'),
    F('baby_dob', 'Baby DOB (DDMMMYY)', 'date'),
    F('delivery_outcome', 'Delivery outcomes'),
    F('weight', 'Weight (Kg)', 'number'),
    F('dob', "Mother's Date of birth (DDMMMYY)", 'date'),
    F('dsdm', 'DSDM approach'),
    F('last_encounter', 'Last Encounter Date DDMMMYY', 'date'),
    F('next_appt', 'Next Appointment date DDMMMYY', 'date'),
    F('followup_outcome', 'Follow up outcomes'),
    F('chw', 'CHW attached to PLHIV (CLF/YAP/PEER):'),
    F('chw_phone', 'CLF/ YAP phone No:'),
    F('chw_last_contact', 'Last Community contact Date with CHW DDMMMYY', 'date'),
    F('chw_next_contact', 'Next Community contact date with CHW DDMMMYY', 'date'),
    F('address_status', 'MBP address Status at contact'),
    ...HIV_CORE,
    F('nvp', 'NVP at birth (Y/N)'),
    F('ctx_age_wks', 'Age of start of CTX(wks)', 'number'),
    F('pcr1_date', 'Sample Collection date (dd/mm/yyyy)', 'date'),
    F('pcr1_result', '1st PCR Result'),
    F('pcr1_given', 'Date result was given to care giver (dd/mm/yy)', 'date'),
    F('enhanced_prophylaxis', 'Enhance ART prophylaxis (If baby is bled beyond 6 weeks)'),
    F('pcr2_date', 'Sample Collection date (dd/mm/yyyy)', 'date'),
    F('pcr2_result', '9mths PCR Result'),
    F('pcr2_given', 'Date result given to care giver (dd/mm/yy)', 'date'),
    F('bf_stopped', 'Date(dd/mm/yy) when breastfeeding stopped', 'date'),
    F('pcr3_date', 'Sample Collection date (dd/mm/yyyy)', 'date'),
    F('pcr3_result', 'PCR Result after Breastfeeding'),
    F('pcr3_given', 'Date result given to care giver (dd/mm/yyyy)', 'date'),
    F('rapid_date', 'Sampling collection date(dd/mm/yy)', 'date'),
    F('rapid_result', 'Results (Negative/Positive)'),
    F('infant_art_no', 'Linkage : ART No. of positive infant'),
    F('final_outcome', 'Final outcome'),
    F('ganc', 'MBP <25 yrs enrolled in Group ANC'),
    F('family_connect', 'On family connect'),
    F('ovc_screening', 'OVC Screening'),
    F('ovc_enrolment', 'OVC enrolment'),
    F('comments', 'Comments'),
  ],
  derive: (r, ref, order) => ({
    ...hivDerive(r, ref, order, { vlThreshold: 200, pmtct: true }),
    ...infantDerive(r, ref, order, true),
  }),
  services: [
    ...hivServices({ vlThreshold: 200, key: 'pmtct' }),
    {
      key: 'eid_enrolment',
      label: 'EID enrolment of the baby',
      eval: (r) => (pregnant(r.category) ? 'NE' : blank(r.baby_eid_no) ? 'Y' : 'N'),
    },
    {
      key: 'nvp',
      label: 'NVP prophylaxis',
      /* The workbook compares the baby's EID number, not the client category,
         with "PMTCT(pregnant)", so pregnant women were never excluded. */
      eval: (r) => {
        if (pregnant(r.category)) return 'NE';
        if (blank(r.nvp) || /never|not given/i.test(txt(r.nvp))) return 'Y';
        if (/completed/i.test(txt(r.nvp))) return 'N';
        return 'ON';
      },
    },
    ...milestones(),
    {
      key: 'final_outcome',
      label: 'Final outcome at 18 months',
      eval: (r, d) => (d.baby_age_months === null || d.baby_age_months < 18 ? 'NE'
        : blank(r.final_outcome) ? 'Y' : 'N'),
    },
    {
      key: 'infant_linkage',
      label: 'Linkage of HIV+ babies to ART',
      /* Linkage is the infant's ART number (BY); the workbook tested the final
         outcome (BZ) instead. */
      eval: (r) => {
        const pos = ['pcr1_result', 'pcr2_result', 'pcr3_result', 'rapid_result'].some((k) => is(r[k], 'Positive'));
        if (!pos) return 'NE';
        return blank(r.infant_art_no) ? 'Y' : 'N';
      },
    },
    {
      key: 'ovc_screening',
      label: 'OVC screening',
      eval: (r) => (/not eligible/i.test(txt(r.ovc_screening)) ? 'NE'
        : /enrolled on|eligible but/i.test(txt(r.ovc_screening)) ? 'N' : 'Y'),
    },
    {
      key: 'ovc_enrolment',
      label: 'OVC enrolment',
      eval: (r) => (/eligible but/i.test(txt(r.ovc_screening)) ? 'Y'
        : /enrolled on/i.test(txt(r.ovc_screening)) ? 'N' : 'NE'),
    },
    {
      key: 'ganc',
      label: 'Group ANC (mothers under 25)',
      eval: (r, d) => (is(r.ganc, 'NE') || (d.age !== null && d.age >= 25) ? 'NE'
        : is(r.ganc, 'Y', 'Yes') ? 'N' : 'Y'),
    },
    {
      key: 'family_connect',
      label: 'Family Connect',
      eval: (r) => (is(r.family_connect, 'NE') ? 'NE' : is(r.family_connect, 'Y', 'Yes') ? 'N' : 'Y'),
    },
    { key: 'art_linkage', label: 'ART initiation of new positives', eval: (r) => linkage(r) },
    { key: 'address', label: 'Address confirmed at contact', eval: (r) => (blank(r.address_status) ? 'Y' : 'N') },
  ],
};

const EID = {
  key: 'eid',
  label: 'EID audit',
  short: 'EID',
  population: 'HIV-exposed infants and their mothers, from the ANC, maternity, YCC and EID registers.',
  workbook: 'EID AUDIT TOOL.xlsx',
  sheet: 'EID Audit Tool',
  idField: 'baby_eid_no',
  vlThreshold: 1000,
  fields: [
    F('ip', 'IP Name'),
    F('district', 'District'),
    F('facility', 'HF Name', 'text', { aliases: ['Facility Name'] }),
    F('source', 'Data source registers: ANC, MAT,YCC, EID'),
    F('initial_encounter', 'Initial encounter date', 'date'),
    F('pmtct_code', "Mother's PMTCT code (TRR,TRRK ETC.)"),
    F('mother_id', 'Mother ID No.'),
    F('art_no', 'Mother ART no:'),
    F('mother_facility', 'Facility where mother gets HIV care'),
    F('subcounty', 'Sub county'),
    F('parish', 'KAGE'),
    F('village', 'Village'),
    F('art_start', 'ART START DATE', 'date'),
    F('vl_result', 'Current VL result'),
    F('vl_date', 'Date of current VL result', 'date'),
    F('risk', 'mother risk assessment'),
    F('vl_updated', 'Is VL updated? Y/N/NE'),
    F('edd', 'EDD (MM/YY)', 'date'),
    F('baby_dob', 'DOB (DD/MM/YY)', 'date'),
    F('baby_status', 'BABY (Alive/Other)'),
    F('baby_eid_no', 'If Live Baby, state EID No (e.g. m/y/001).', 'text', { aliases: ['EID No'] }),
    F('eid_facility', 'EID care facility NAME'),
    F('last_encounter', 'Last encounter date', 'date'),
    F('next_appt', 'Next appt date', 'date'),
    F('nvp', 'NVP at birth (Y/N)'),
    F('ctx_age_wks', 'Age of start of CTP(wks)', 'number'),
    F('pcr1_date', 'Sample Collection date (dd/mm/yyyy)', 'date'),
    F('pcr1_result', '1st PCR Result'),
    F('pcr1_given', 'Date result given to care giver (dd/mm/yy)', 'date'),
    F('enhanced_prophylaxis', 'Enhance ART prophylaxis (If baby is bled beyond 6 weeks)'),
    F('pcr2_date', 'Sample Collection date (dd/mm/yyyy)', 'date'),
    F('pcr2_result', '2ND PCR Result'),
    F('pcr2_given', 'Date result given to care giver (dd/mm/yy)', 'date'),
    F('bf_stopped', 'Date(dd/mm/yy) when breastfeeding stopped', 'date'),
    F('pcr3_date', 'Sample Collection date (dd/mm/yyyy)', 'date'),
    F('pcr3_result', '3ND PCR Result'),
    F('pcr3_given', 'Date result given to care giver (dd/mm/yyyy)', 'date'),
    F('rapid_date', 'Sampling collection date(dd/mm/yy)', 'date'),
    F('rapid_result', 'Results (N/P)'),
    F('rapid_given', 'Date result given to care giver (dd/mm/yyyy)', 'date'),
    F('infant_art_no', 'Linkage : ART No. of positive infant'),
    F('status', 'STATUS'),
    F('ovc_screening', 'OVC screening assessment'),
    F('ovc_id', 'If enrolled to OVC/CSO, State ID number at OVC/CSO'),
    F('chw', 'CLF/ YAP attached to MBP:'),
    F('chw_phone', 'CLF/ YAP phone No:'),
  ],
  derive: (r, ref, order) => ({
    ...infantDerive(r, ref, order, false),
    status: txt(r.status),
    _order: order,
  }),
  services: [
    {
      key: 'mother_art',
      label: 'Enrol mother on ART',
      eval: (r) => (is(r.pmtct_code, 'TRR') && blank(r.art_no) ? 'Y' : 'N'),
    },
    {
      key: 'anc_followup',
      label: 'ANC mother follow-up (delivery not recorded)',
      eval: (r, d, ref) => {
        // No delivery recorded and the EDD passed - or no EDD at all, which
        // the workbook also flags (a blank compares as day zero).
        const edd = parseDate(r.edd, d._order);
        return blank(r.baby_dob) && (!edd || edd <= ref) ? 'Y' : 'N';
      },
    },
    {
      key: 'eid_enrolment',
      label: 'EID enrolment',
      eval: (r) => (/alive/i.test(txt(r.baby_status)) && !blank(r.baby_dob) && blank(r.baby_eid_no) ? 'Y' : 'N'),
    },
    {
      key: 'mbp_followup',
      label: 'Mother-baby pair follow-up',
      eval: (r, d, ref) => {
        const next = parseDate(r.next_appt, d._order);
        return next && next <= ref && d.baby_age_months !== null && d.baby_age_months < 24 ? 'Y' : 'N';
      },
    },
    { key: 'mother_vl', label: 'VL sampling for mother', eval: (r) => (is(r.vl_updated, 'N') ? 'Y' : 'N') },
    {
      key: 'nvp',
      label: 'Start NVP',
      /* The workbook tests for "Yes", which its NVP dropdown never offers, so
         this service could not show a gap. "Not given" is the gap. */
      eval: (r) => (blank(r.baby_dob) ? 'NE'
        : blank(r.nvp) || /not given|^no?$/i.test(txt(r.nvp)) ? 'Y' : 'N'),
    },
    ...milestones().filter((m) => !m.key.endsWith('_results')),
    {
      key: 'results_given',
      label: 'Give caregiver results',
      eval: (r) => {
        const pairs = [['pcr1_result', 'pcr1_given'], ['pcr2_result', 'pcr2_given'],
          ['pcr3_result', 'pcr3_given'], ['rapid_result', 'rapid_given']];
        if (!pairs.some(([res]) => !blank(r[res]))) return 'NE';
        return pairs.some(([res, g]) => !blank(r[res]) && blank(r[g])) ? 'Y' : 'N';
      },
    },
    {
      key: 'ovc_screening',
      label: 'OVC screening',
      // Like every infant column in the workbook, nothing is owed until the
      // baby is born (IF(S2="","",...)).
      eval: (r) => (blank(r.baby_dob) ? 'NE'
        : blank(r.ovc_screening) || /never/i.test(txt(r.ovc_screening)) ? 'Y' : 'N'),
    },
    {
      key: 'ovc_enrolment',
      label: 'OVC enrolment',
      /* The workbook's OR(enrolled, no ID) marked every enrolled infant as a
         gap. The gap is an eligible infant not enrolled, or enrolled with no
         OVC/CSO number to show for it. */
      eval: (r) => {
        const s = txt(r.ovc_screening);
        if (blank(r.baby_dob)) return 'NE';
        if (/eligible but/i.test(s)) return 'Y';
        if (/^enrolled/i.test(s)) return blank(r.ovc_id) ? 'Y' : 'N';
        return 'NE';
      },
    },
    {
      key: 'hts_24m',
      label: 'Follow up baby and provide HTS (24 months+)',
      eval: (r, d, ref) => {
        const next = parseDate(r.next_appt, d._order);
        return next && next <= ref && d.baby_age_months !== null && d.baby_age_months >= 24 ? 'Y' : 'N';
      },
    },
  ],
};

export const TOOLS = { adult: ADULT, pmtct: PMTCT, eid: EID };
export const TOOL_ORDER = ['adult', 'pmtct', 'eid'];

/* Which clients count as "in care" for the service cascades. The workbooks
   count Active, Missed Appointment and Early IIT, and so does this. EID
   status is entered by hand rather than computed. */
export function inCare(tool, rec) {
  if (tool.key === 'eid') return /^(active|missed appointment)$/i.test(txt(rec.derived.status));
  return IN_CARE.includes(rec.derived.status);
}

/* ---------------------------------------------------------------- the list */

const headerKey = (h) => txt(h).toLowerCase()
  .replace(/[‘’]/g, "'")
  .replace(/[^a-z0-9<>+/']+/g, ' ')
  .trim();

/**
 * Map a file's header row onto a tool's fields.
 *
 * Accepts the workbook's own header text (a filled audit sheet saved as CSV),
 * the field keys (an EMR extract), or a known alias. Several PMTCT and EID
 * headers repeat - "Sample Collection date" appears three times - so a header
 * is matched to the first field of that name not already taken, which is the
 * workbook's own left-to-right order.
 *
 * Returns { map: {fileIndex: fieldKey}, missing: [fieldKey], unknown: [header] }.
 */
export function mapHeaders(tool, headers) {
  const taken = new Set();
  const map = {};
  const unknown = [];
  headers.forEach((h, i) => {
    const k = headerKey(h);
    if (!k) {
      const byPos = tool.blankHeaders && tool.blankHeaders[i];
      if (byPos && !taken.has(byPos)) { map[i] = byPos; taken.add(byPos); }
      return;
    }
    const exact = tool.fields.find((f) => !taken.has(f.key)
      && [f.key, f.header, ...(f.aliases || [])].some((c) => headerKey(c) === k));
    const field = exact || (k.length > 18 && tool.fields.find((f) => {
      const fk = headerKey(f.header);
      return !taken.has(f.key) && fk.length > 18 && (fk.startsWith(k.slice(0, 18)) || k.startsWith(fk.slice(0, 18)));
    }));
    if (field) {
      map[i] = field.key;
      taken.add(field.key);
    } else unknown.push(txt(h));
  });
  const missing = tool.fields.filter((f) => !taken.has(f.key)).map((f) => f.key);
  return { map, missing, unknown };
}

/** Parse CSV text (comma, semicolon or tab; quoted fields; BOM; CRLF). */
export function parseCSV(text) {
  const src = String(text || '').replace(/^﻿/, '');
  const firstLine = src.split(/\r?\n/, 1)[0] || '';
  const delim = [',', ';', '\t'].map((d) => [d, firstLine.split(d).length])
    .sort((a, b) => b[1] - a[1])[0][0];
  const rows = [];
  let row = [];
  let cell = '';
  let q = false;
  for (let i = 0; i < src.length; i += 1) {
    const c = src[i];
    if (q) {
      if (c === '"') {
        if (src[i + 1] === '"') { cell += '"'; i += 1; } else q = false;
      } else cell += c;
    } else if (c === '"') q = true;
    else if (c === delim) { row.push(cell); cell = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && src[i + 1] === '\n') i += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else cell += c;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((c) => txt(c)));
}

/** Rows (arrays) plus a header mapping -> objects keyed by field. Rows with
 *  no identifier are dropped, as the workbooks drop them (every formula opens
 *  with IF(D2="","",...)). */
export function toRecords(tool, rows, map) {
  const out = [];
  for (const cells of rows) {
    const r = {};
    Object.entries(map).forEach(([i, k]) => { r[k] = cells[+i] ?? ''; });
    const id = tool.key === 'eid' ? (r.baby_eid_no || r.mother_id || r.art_no || r.baby_dob) : r[tool.idField];
    if (!blank(id)) out.push(r);
  }
  return out;
}

/**
 * Audit a line list.
 *
 * @param tool   one of TOOLS
 * @param rows   objects keyed by field
 * @param opts   { ref: the audit date (the workbooks use TODAY(), which
 *                      makes last month's audit unrepeatable - this takes
 *                      the date as an input instead),
 *                 order: 'DMY' | 'MDY' for slashed dates }
 */
export function audit(tool, rows, opts = {}) {
  const ref = parseDate(opts.ref || new Date());
  const dateKeys = tool.fields.filter((f) => f.type === 'date').map((f) => f.key);
  const order = opts.order || detectDateOrder(rows, dateKeys).order;
  const records = rows.map((r) => {
    const derived = tool.derive(r, ref, order);
    const flags = {};
    for (const s of tool.services) flags[s.key] = s.eval(r, derived, ref);
    const rec = { input: r, derived, flags };
    rec.inCare = inCare(tool, rec);
    rec.outstanding = tool.services.filter((s) => flags[s.key] === 'Y').map((s) => s.key);
    return rec;
  });
  return {
    tool: tool.key,
    ref: iso(ref),
    order,
    records,
    summary: summarise(tool, records),
    corrections: CORRECTIONS[tool.key],
  };
}

const count = (arr, fn) => arr.reduce((n, x) => n + (fn(x) ? 1 : 0), 0);
const pct = (a, b) => (b ? Math.round((a / b) * 1000) / 10 : null);

/** Cohort, service cascades and the tool-specific indicators. */
export function summarise(tool, records) {
  const care = records.filter((r) => r.inCare);
  const cascades = tool.services.map((s) => {
    const c = { Y: 0, N: 0, ON: 0, NE: 0, NA: 0 };
    for (const r of care) c[r.flags[s.key]] = (c[r.flags[s.key]] || 0) + 1;
    const eligible = c.Y + c.N + c.ON;
    return {
      key: s.key,
      label: s.label,
      eligible,
      given: c.N,
      underway: c.ON,
      outstanding: c.Y,
      notEligible: c.NE + c.NA,
      coverage: pct(c.N + c.ON, eligible),
    };
  });
  const cohort = [];
  const push = (label, n, of, indent = false) => cohort.push({ label, n, of: of ?? null, pct: of === undefined ? null : pct(n, of), indent });
  push('Clients on the line list', records.length);
  if (tool.key === 'eid') {
    const st = (re) => count(records, (r) => re.test(txt(r.derived.status)));
    push('Currently in care (Active or Missed Appointment)', care.length, records.length);
    push('Died', st(/^dead|died/i), records.length);
    push('Transferred out', st(/^to$|transfer/i), records.length);
    push('Dropped', st(/dropped/i), records.length);
    push('Lost to follow-up', st(/ltfu|lost/i), records.length);
    push('Linked to ART (moved to C&A clinic)', st(/linked to art/i), records.length);
    push('Discharged negative', st(/discharged/i), records.length);
  } else {
    const st = (s) => count(records, (r) => r.derived.status === s);
    const lost = records.filter((r) => ['Defaulter', 'Late IIT'].includes(r.derived.status));
    const outcome = (re) => count(lost, (r) => re.test(txt(r.input.followup_outcome)));
    push('In care (Active, Missed Appointment, Early IIT)', care.length, records.length);
    push('Active', st('Active'), records.length, true);
    push('Missed appointment (1-7 days)', st('Missed Appointment'), records.length, true);
    push('Early interruption (8-28 days)', st('Early IIT'), records.length, true);
    push('Late interruption (29-90 days)', st('Late IIT'), records.length);
    push('Defaulter (over 90 days)', st('Defaulter'), records.length);
    push('Late IIT and defaulters with a follow-up outcome', count(lost, (r) => !blank(r.input.followup_outcome)), lost.length);
    push('Transferred out', outcome(/^transfer out/i), lost.length, true);
    push('Self-transferred', outcome(/self transfer/i), lost.length, true);
    push('Died', outcome(/^died/i), lost.length, true);
    push('Stopped or refused', outcome(/stopped|refused/i), lost.length, true);
    push('Could not be located', outcome(/unable to locate/i), lost.length, true);
    push('No next appointment date recorded', count(records, (r) => !r.derived.status), records.length);
    push('In care aged under 20 (belongs on the C&A tool)', count(care, (r) => r.derived.age_group === '<20'), care.length);
    push('In care aged 20-24', count(care, (r) => r.derived.age_group === '20-24'), care.length);
    push('In care aged 25-54', count(care, (r) => r.derived.age_group === '25-54'), care.length);
    push('In care aged 55 and over', count(care, (r) => r.derived.age_group === '55+'), care.length);
    push('Without a date of birth', count(records, (r) => r.derived.without_dob), records.length);
    const vlElig = care.filter((r) => r.derived.vl_updated !== 'NE');
    push('Due a viral load, with a current result', count(vlElig, (r) => r.derived.vl_updated === 'Y'), vlElig.length);
    const withVl = care.filter((r) => vlClass(r.input.vl_result, tool.vlThreshold));
    push(`Suppressed (below ${tool.vlThreshold.toLocaleString('en-GB')} copies/mL)`,
      count(withVl, (r) => vlClass(r.input.vl_result, tool.vlThreshold) === 'suppressed'), withVl.length);
    push('On a DTG-based regimen', count(care, (r) => r.derived.on_dtg === 'Y'), care.length);
  }
  push('In care and owed no service', count(care, (r) => r.outstanding.length === 0), care.length);
  return { inCare: care.length, cohort, cascades, eid: tool.key === 'eid' ? eidIndicators(records) : null };
}

/** The EID workbook's programme indicators, by the infant's age on the audit
 *  date. */
function eidIndicators(records) {
  const age = (r) => r.derived.baby_age_months;
  const has = (r, k) => !blank(r.input[k]);
  const positive = (r) => ['pcr1_result', 'pcr2_result', 'pcr3_result', 'rapid_result']
    .some((k) => /^p/i.test(txt(r.input[k])));
  const row = (label, n, d) => ({ label, num: n, den: d, pct: pct(n, d) });
  const sampled1 = records.filter((r) => has(r, 'pcr1_date'));
  const u2 = records.filter((r) => age(r) !== null && age(r) <= 2);
  const at9 = records.filter((r) => age(r) >= 9 && age(r) < 10);
  const at18 = records.filter((r) => age(r) >= 18 && age(r) < 19);
  const positives = records.filter(positive);
  const nvpGiven = (r) => /given/i.test(txt(r.input.nvp)) && !/not given/i.test(txt(r.input.nvp));
  return [
    row('1st DNA PCR taken within 0-2 months of age', count(sampled1, (r) => {
      const d = parseDate(r.input.pcr1_date, r.derived._order);
      const b = parseDate(r.input.baby_dob, r.derived._order);
      return d && b && (d - b) / DAY / 30 <= 2;
    }), sampled1.length),
    row('Infants 0-2 months who received NVP', count(u2, nvpGiven), u2.length),
    row('Infants 0-2 months started on CPT', count(u2, (r) => has(r, 'ctx_age_wks')), u2.length),
    row('Infants aged 9 months with a 2nd DNA PCR', count(at9, (r) => has(r, 'pcr2_date')), at9.length),
    row('Infants aged 18 months with a rapid test result', count(at18, (r) => has(r, 'rapid_result')), at18.length),
    row('HIV-positive infants under 2 years linked to ART',
      count(positives, (r) => age(r) !== null && age(r) <= 24 && has(r, 'infant_art_no')), positives.length),
    row('Never screened for OVC',
      count(records, (r) => blank(r.input.ovc_screening) || /never/i.test(txt(r.input.ovc_screening))), records.length),
    row('Enrolled on OVC care', count(records, (r) => /^enrolled/i.test(txt(r.input.ovc_screening))), records.length),
  ];
}

/* ------------------------------------------------------------------ export */

const csvCell = (v) => {
  const s = v instanceof Date ? iso(v) : v === null || v === undefined ? '' : String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
export const toCSV = (rows) => `${rows.map((r) => r.map(csvCell).join(',')).join('\r\n')}\r\n`;

/** The completed line list: the workbook's entry columns, then what this
 *  module derived, then one column per service - the shape of the workbook's
 *  own sheet once its formulas have run. */
export function exportLineList(tool, result) {
  const derivedKeys = Object.keys(result.records[0]?.derived || {}).filter((k) => !k.startsWith('_'));
  const head = [...tool.fields.map((f) => f.header), ...derivedKeys,
    ...tool.services.map((s) => s.label), 'Services outstanding'];
  const body = result.records.map((r) => [
    ...tool.fields.map((f) => r.input[f.key] ?? ''),
    ...derivedKeys.map((k) => r.derived[k]),
    ...tool.services.map((s) => r.flags[s.key]),
    r.inCare ? r.outstanding.length : '',
  ]);
  return toCSV([head, ...body]);
}

/** One row per client in care who is owed at least one service, most owed
 *  first. */
export function worklist(tool, result) {
  return result.records
    .filter((r) => r.inCare && r.outstanding.length)
    .sort((a, b) => b.outstanding.length - a.outstanding.length);
}

export function exportWorklist(tool, result) {
  const label = Object.fromEntries(tool.services.map((s) => [s.key, s.label]));
  const idLabel = tool.fields.find((f) => f.key === tool.idField)?.header || 'ID';
  const head = [idLabel, 'Facility', 'Status', 'Next appointment', 'CHW', 'CHW phone', 'Outstanding', 'Services owed'];
  const body = worklist(tool, result).map((r) => [
    r.input[tool.idField] || r.input.mother_id || '', r.input.facility || '', r.derived.status || '',
    r.input.next_appt || '', r.input.chw || '', r.input.chw_phone || '',
    r.outstanding.length, r.outstanding.map((k) => label[k]).join('; '),
  ]);
  return toCSV([head, ...body]);
}

/** A blank CSV with the workbook's entry headers, for a team that would
 *  rather fill a sheet by hand than run the extract. */
export function templateCSV(tool) {
  return toCSV([tool.fields.map((f) => f.header)]);
}

/* ------------------------------------------------------------- corrections */

export const CORRECTIONS = {
  adult: [
    'Viral load currency: the workbook tests the category for "Adult client", which its own dropdown never offers, so every adult on ART six months or more read as not up to date. Adults are now held to a 12-month window, pregnant and breastfeeding women to 6.',
    'Cancer treatment: OR(x<>"a", x<>"b") is always true, so the column could only ever read NE. A positive, untreated client now reads as outstanding.',
    '"# Died" counted self-transfers (a copied formula). It now counts deaths.',
    'Switch eligibility read row 4 of the BackEnd for every client (M4, not M2). Each client is now read against their own HIVDR result.',
    'ART initiation of new positives compared known-status counts with positives. It now asks whether every child or partner found positive is on ART.',
    'Follow-up read N (done) for every Active client, which filled the follow-up cascade with clients who were never lost. Active clients now read as not applicable.',
    'Cervical screening is limited to women aged 25-54 who have not yet been screened; the workbook left that to the dropdown, so unscreened women outside the age band read as a gap.',
    'Clients under 20 were grouped as 20-24. They are now shown as "<20" so they can be found and moved to the C&A tool.',
  ],
  pmtct: [
    'Start NVP compared the baby\'s EID number, not the client category, with "PMTCT(pregnant)", so pregnant women were never excluded. The category is now used.',
    'The first PCR fell due at four weeks (DOB + 28). The national schedule and the EID workbook both say six weeks, so six is used.',
    'Cervical cancer eligibility read sex from a deleted column (#REF!). Every client is a mother, so women aged 25-54 are eligible.',
    'Cancer screening returned " Y" with a leading space, which no count could match.',
    'Infant linkage tested the final outcome column; it now tests the infant\'s ART number.',
    'OVC enrolment marked enrolled mothers as the gap. It now marks those eligible but not enrolled.',
    'The ReadMe sheet is the C&A tool\'s and describes different columns. The column map here follows the PMTCT sheet itself.',
    'This workbook uses 200 copies/mL as its suppression threshold, where the Adult and EID tools use 1,000. It is kept as the workbook has it.',
  ],
  eid: [
    'Start NVP tested for "Yes", which the NVP dropdown never offers, so no infant could show as owed NVP. "Not given" now reads as outstanding.',
    'OVC enrolment used OR(enrolled, no ID), which marked every enrolled infant as a gap. It now marks eligible infants not enrolled, and enrolled infants with no OVC/CSO number.',
    'Give caregiver results tested the enhanced-prophylaxis column (AH) for the first PCR, not the date the result was given (AG), so most infants whose results had been handed over still read as owed. The date given is now used.',
    'NVP coverage counted NVP = "Yes" and so was always nil. It now counts either "Given" option.',
    'CPT coverage divided by infants with a first PCR rather than infants aged 0-2 months. It now uses the age group.',
  ],
};
