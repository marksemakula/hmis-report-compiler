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
 * intended — typically a literal path swallowed by an earlier parameterised one
 * — so that case is called out by name rather than left as a validation message
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
        // loc starts with the location kind — body, query, path, header,
        // cookie — which tells the reader nothing they need. Keep the field.
        const KINDS = new Set(['body', 'query', 'path', 'header', 'cookie']);
        const where = Array.isArray(d?.loc) ? d.loc.filter((s) => !KINDS.has(s)).join('.') : '';
        const msg = d?.msg || d?.type || 'invalid value';
        return where ? `${where}: ${msg}` : msg;
      })
      .filter(Boolean);
    const joined = parts.join('; ');
    if (status === 422) {
      return `The server rejected this request as malformed (422)`
        + (joined ? ` — ${joined}.` : '.')
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
