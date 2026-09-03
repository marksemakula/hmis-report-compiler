/* Checks for the shared client helpers in app/lib.js.
 *
 * The reason this file exists: a 422 from FastAPI carries `detail` as an ARRAY
 * of objects, and `new Error(body.detail)` renders that as the useless string
 * "[object Object]". That is precisely what hid a routing fault for several
 * rounds of debugging. Every branch below asserts a person could act on what
 * they are shown.
 *
 *   node scripts/test_client.mjs
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'app', 'lib.js'), 'utf8');
const mod = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));
const { describeError } = mod;

const failures = [];
function check(label, got, want) {
  const ok = typeof want === 'function' ? want(got) : got === want;
  if (!ok) {
    failures.push(`${label}\n     wanted: ${want}\n     got:    ${JSON.stringify(got)}`);
    console.log(`  FAIL  ${label}`);
  } else {
    console.log(`  ok    ${label}`);
  }
}
const has = (s) => (got) => typeof got === 'string' && got.includes(s);
const lacks = (s) => (got) => typeof got === 'string' && !got.includes(s);

console.log('\nThe bug that started this: a 422 validation array');
const four22 = {
  detail: [{
    type: 'int_parsing',
    loc: ['path', 'report_id'],
    msg: 'Input should be a valid integer, unable to parse string as an integer',
    input: 'types',
  }],
};
const msg = describeError(422, four22, 'Could not load the report list');
check('never renders [object Object]', msg, lacks('[object Object]'));
check('names the status', msg, has('422'));
check('carries the underlying message', msg, has('valid integer'));
check('names the parameter', msg, has('report_id'));
check('points at the likely cause', msg, has('stale browser cache'));

console.log('\nOther shapes the API actually returns');
check('plain HTTPException string',
  describeError(401, { detail: 'Session expired - please sign in again' }, 'x'),
  'Session expired - please sign in again');
check('multiple validation problems are joined',
  describeError(422, { detail: [{ loc: ['body', 'a'], msg: 'required' }, { loc: ['body', 'b'], msg: 'too long' }] }, 'x'),
  (g) => g.includes('a: required') && g.includes('b: too long'));
check('non-422 array detail stays plain',
  describeError(400, { detail: [{ loc: ['query', 'period'], msg: 'bad period' }] }, 'x'),
  'period: bad period');
check('detail array of bare strings',
  describeError(400, { detail: ['first problem', 'second problem'] }, 'x'),
  'first problem; second problem');
check('object detail is serialised, not stringified to [object Object]',
  describeError(500, { detail: { code: 'E1', hint: 'retry' } }, 'x'),
  (g) => g.includes('E1') && !g.includes('[object Object]'));
check('body.error is honoured',
  describeError(500, { error: 'Blob storage unavailable' }, 'x'),
  'Blob storage unavailable');

console.log('\nNon-JSON and empty responses');
check('an HTML error page falls back rather than dumping markup',
  describeError(502, '<!doctype html><html><body>Bad gateway</body></html>', 'Preview unavailable'),
  'Preview unavailable (HTTP 502)');
check('a plain-text body is shown',
  describeError(500, 'upstream timed out', 'x'), 'upstream timed out');
check('null body falls back with the status',
  describeError(503, null, 'Preview unavailable'), 'Preview unavailable (HTTP 503)');
check('empty detail falls back',
  describeError(500, { detail: '' }, 'Request failed'), 'Request failed (HTTP 500)');
check('empty array detail falls back',
  describeError(500, { detail: [] }, 'Request failed'), 'Request failed (HTTP 500)');

console.log('\nNo input produces the string that started all this');
const shapes = [
  null, undefined, '', '   ', {}, { detail: null }, { detail: [] }, { detail: {} },
  { detail: [{}] }, { detail: [null] }, { detail: 42 }, { detail: [{ msg: null }] },
  '<html></html>', 'text', { error: '' }, { detail: [{ loc: null, msg: 'x' }] },
];
let clean = true;
for (const s of shapes) {
  for (const status of [400, 401, 422, 500, 502]) {
    const out = describeError(status, s, 'Request failed');
    if (typeof out !== 'string' || out.includes('[object Object]') || out.trim() === '') {
      clean = false;
      console.log(`  FAIL  status ${status}, body ${JSON.stringify(s)} -> ${JSON.stringify(out)}`);
    }
  }
}
check(`${shapes.length} body shapes x 5 statuses all yield readable text`, clean, true);

console.log('\nWeek labels must agree with the server\'s ISO calendar');
// The picker labels each week with the dates it covers - "Week 35
// (2026-08-24 - 2026-08-30)". Those dates are computed in the browser while
// the extract's date filter is computed in Python, so the two arithmetics have
// to agree exactly. A week mislabelled by one day would have someone extract a
// period they did not intend and never see it.
//
// ISO-8601 anchors week 1 on the week containing 4 January, so a year's first
// week can begin in the previous December, and some years carry 53 weeks.
// Both are checked below against a table generated from Python's
// date.fromisocalendar, which is what api/_lib/periods.py uses.
const weekFns = mod;  // isoWeek, weeksInYear, isoWeekMonday, weekLabel

// Generated by: date.fromisocalendar(y, w, 1) and (y, w, 7), 2015-2035.
const table = JSON.parse(readFileSync(join(here, 'iso_weeks.json'), 'utf8'));
let weeksChecked = 0;
const weekBad = [];
for (const [year, weeks] of Object.entries(table)) {
  const n = weekFns.weeksInYear(Number(year));
  if (n !== Object.keys(weeks).length) weekBad.push(`${year}: ${n} weeks, expected ${Object.keys(weeks).length}`);
  for (const [w, [mon, sun]] of Object.entries(weeks)) {
    const want = `Week ${w} (${mon} - ${sun})`;
    const got = weekFns.weekLabel(Number(year), Number(w));
    if (got !== want) weekBad.push(`${year}W${w}: ${got} != ${want}`);
    weeksChecked++;
  }
}
check(`${weeksChecked} weeks across 21 years match the server exactly`, weekBad.length, 0);
if (weekBad.length) weekBad.slice(0, 5).forEach((b) => console.log('      ' + b));
check('the format is the one asked for', weekFns.weekLabel(2026, 35),
      'Week 35 (2026-08-24 - 2026-08-30)');
check('week 1 of 2026 opens in December 2025, per ISO-8601',
      weekFns.weekLabel(2026, 1), 'Week 1 (2025-12-29 - 2026-01-04)');
check('a 53-week year offers all 53', weekFns.weeksInYear(2026), 53);
check('a 52-week year offers 52', weekFns.weeksInYear(2025), 52);

/* Every report says what file it takes, next to the file picker.
 *
 * The week-35 tally was uploaded as July 2026 105:01 and came back as
 * seventeen rows each missing a PatientNo. The server now names the mismatch;
 * this line is meant to prevent it. A report added without a `takes` would
 * render "undefined" under the file input, which is worse than saying nothing.
 */
console.log('\nThe upload panel says what file each report takes');
/* The compile workflow moved from / to /compile when the dashboard took the
   landing page. It is the same file; only its directory changed. */
const page = readFileSync(join(here, '..', 'app', 'compile', 'page.js'), 'utf8');
const reportsBlock = page.slice(page.indexOf('const REPORTS = {'),
                                page.indexOf('export default function'));
for (const key of ['OPD:', 'IPD:', 'SURV:']) {
  const entry = reportsBlock.slice(reportsBlock.indexOf(key));
  const upto = entry.slice(0, entry.indexOf('},'));
  check(`${key.replace(':', '')} declares what it takes`, /takes:\s*'/.test(upto), true);
}
check('and the hint is rendered under the file picker',
      page.includes('REPORTS[reportType].takes'), true);
check('no em dash in the hints', /—/.test(reportsBlock), false);

console.log();
if (failures.length) {
  console.log(`${failures.length} check(s) failed:\n`);
  failures.forEach((f) => console.log('  - ' + f));
  process.exit(1);
}
console.log('All checks passed.');
