/* Shared client helpers. */

/**
 * Turn an API failure into a sentence a person can act on.
 *
 * FastAPI returns two quite different shapes and conflating them is how you end
 * up staring at "[object Object]":
 *
 *   HTTPException  -> { detail: "The email address or password is incorrect" }
 *   422 validation -> { detail: [ { loc: ["path","report_id"], msg: "Input should
 *                                   be a valid integer", type: "int_parsing" } ] }
 *
 * A 422 on a GET almost always means the URL matched a different route than
 * intended - typically a literal path swallowed by an earlier parameterised one
 * - so that case is called out by name rather than left as a validation message
 * about a parameter the caller never knowingly supplied.
 */
export function describeError(status, body, fallback = 'Request failed') {
  if (typeof body === 'string' && body.trim()) {
    const text = body.trim();
    return text.startsWith('<') ? `${fallback} (HTTP ${status})` : text;
  }

  const detail = body && body.detail;

  if (typeof detail === 'string' && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => {
        if (typeof d === 'string') return d;
        // loc starts with the location kind - body, query, path, header,
        // cookie - which tells the reader nothing they need. Keep the field.
        const KINDS = new Set(['body', 'query', 'path', 'header', 'cookie']);
        const where = Array.isArray(d?.loc) ? d.loc.filter((s) => !KINDS.has(s)).join('.') : '';
        const msg = d?.msg || d?.type || 'invalid value';
        return where ? `${where}: ${msg}` : msg;
      })
      .filter(Boolean);
    const joined = parts.join('; ');
    if (status === 422) {
      return `The server rejected this request as malformed (422)`
        + (joined ? ` - ${joined}.` : '.')
        + ' This usually means the URL reached the wrong endpoint;'
        + ' a stale browser cache is the commonest cause.';
    }
    if (joined) return joined;
  }

  // Arrays are handled above; an empty one carries nothing, so it must fall
  // through to the status fallback rather than rendering as "[]".
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    try {
      const json = JSON.stringify(detail);
      if (json && json !== '{}') return json;
    } catch { /* fall through */ }
  }

  if (body && typeof body.error === 'string' && body.error.trim()) return body.error;

  return `${fallback} (HTTP ${status})`;
}

/** fetch + parse + raise a readable Error. Returns the parsed body on success. */
export async function apiGet(url, fallback) {
  const r = await fetch(url);
  const text = await r.text();
  let body;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!r.ok) {
    const err = new Error(describeError(r.status, body, fallback));
    err.status = r.status;
    throw err;
  }
  return body;
}

/* ------------------------------------------------------------------ periods
 *
 * ISO-8601 week arithmetic, shared by the Compile, Preview and Extraction
 * Scripts pages. It lived in all three as separate copies, which is three
 * places to fix and three places to drift; a week mislabelled on one page and
 * not another is exactly the sort of discrepancy nobody reports and everybody
 * distrusts.
 *
 * These must agree exactly with api/_lib/periods.py, which uses Python's
 * date.fromisocalendar. scripts/test_client.mjs checks all 1,096 weeks from
 * 2015 to 2035 against a table generated from it.
 */

/** [isoYear, isoWeek] for a Date. The ISO year is not always the calendar one. */
export function isoWeek(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return [t.getUTCFullYear(), Math.ceil(((t - yearStart) / 86400000 + 1) / 7)];
}

/** 52 or 53. Some years genuinely have 53 ISO weeks; 2026 is one. */
export function weeksInYear(y) {
  return isoWeek(new Date(y, 11, 28))[1];
}

/**
 * The Monday opening ISO week `week` of `year`.
 *
 * ISO-8601 anchors week 1 on the week containing 4 January, so a year's first
 * week can begin in the previous December - week 1 of 2026 starts on
 * 29 December 2025. A picker that hid that would mislabel every week in January.
 */
export function isoWeekMonday(year, week) {
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const dow = jan4.getUTCDay() || 7;                 // Monday = 1 … Sunday = 7
  return new Date(Date.UTC(year, 0, 4 - (dow - 1)) + (week - 1) * 604800000);
}

/** "Week 35 (2026-08-24 - 2026-08-30)". The end is the Sunday, inclusive: the
 *  query's exclusive bound is the Monday after, and showing that reads as an
 *  extra day. */
export function weekLabel(year, week) {
  const monday = isoWeekMonday(year, week);
  const sunday = new Date(monday.getTime() + 6 * 86400000);
  const ymd = (d) => d.toISOString().slice(0, 10);
  return `Week ${week} (${ymd(monday)} - ${ymd(sunday)})`;
}
