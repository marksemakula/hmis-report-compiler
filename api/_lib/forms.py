"""Official DHIS2 entry forms, rendered read-only.

All eight Uganda HMIS data sets this compiler handles use CUSTOM data entry
forms: rather than letting DHIS2 lay out a grid from sections, the Ministry has
supplied the HTML of the paper form itself. Each cell is an <input> identified
by the DHIS2 convention

    id="{dataElementUID}-{categoryOptionComboUID}-val"

which is exactly the key our compiled data values already carry. So the preview
can render the genuine form with our figures in place, instead of a table of our
own devising. Two things follow from that, and both matter:

  * The preview looks precisely like the entry screen the QA team already
    knows, which is what makes it useful for checking before submission.
  * When the Ministry revises a form, the preview follows on the next metadata
    refresh. Nothing here transcribes 2,752 data elements by hand.

The forms are large — 105:01 is over half a megabyte — so the sanitised
skeleton is cached in Postgres and only the value injection runs per request.

SAFETY: the HTML is third-party. Scripts, event handlers and javascript: URLs
are stripped at cache time, every field becomes an inert span, and the result is
served into a sandboxed iframe. Nothing in a form can execute.
"""
import html as html_lib
import os
import re

import requests

from .metadata import CONSTANTS, mapping

# id="<11-char UID>-<11-char UID>-val" — the DHIS2 data entry convention.
FIELD_ID_RE = re.compile(r'id\s*=\s*"([A-Za-z0-9]{11})-([A-Za-z0-9]{11})-val"', re.I)

_SCRIPT_RE   = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.I | re.S)
_HANDLER_RE  = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_JSURL_RE    = re.compile(r"(href|src)\s*=\s*(\"|')\s*javascript:[^\"']*(\"|')", re.I)
_INPUT_RE    = re.compile(r"<input\b[^>]*>", re.I)
_SELECT_RE   = re.compile(r"<select\b[^>]*>.*?</select\s*>", re.I | re.S)
_TEXTAREA_RE = re.compile(r"<textarea\b[^>]*>.*?</textarea\s*>", re.I | re.S)
_SLOT_RE     = re.compile(r'<span class="hv" data-k="([^"]*)"></span>')

_SKELETONS = {}


def _session():
    s = requests.Session()
    pat = os.environ.get("DHIS2_PAT", "")
    if pat:
        s.headers["Authorization"] = f"ApiToken {pat}"
    else:
        user = os.environ.get("DHIS2_USERNAME", "")
        pwd = os.environ.get("DHIS2_PASSWORD", "")
        if not user or not pwd:
            raise RuntimeError(
                "DHIS2 credentials are not configured, so the official form layouts "
                "cannot be fetched. Set DHIS2_USERNAME and DHIS2_PASSWORD (or DHIS2_PAT)."
            )
        s.auth = (user, pwd)
    s.headers["Accept"] = "application/json"
    return s


def _fetch_form_html(ds_id: str) -> str:
    base = os.environ.get("DHIS2_BASE_URL", CONSTANTS["instance"]).rstrip("/")
    r = _session().get(
        f"{base}/api/dataSets/{ds_id}.json",
        params={"fields": "dataEntryForm[htmlCode]"},
        timeout=90,
    )
    r.raise_for_status()
    form = (r.json() or {}).get("dataEntryForm") or {}
    return form.get("htmlCode") or ""


def sanitise(raw_html: str) -> str:
    """Turn a DHIS2 entry form into an inert skeleton with labelled value slots.

    Every field becomes <span class="hv" data-k="DE-COC"></span>. Fields whose
    id does not follow the DHIS2 convention (running totals the entry app
    computes in the browser, for example) become empty slots with no key, so the
    form's shape is preserved without inventing a figure for them."""
    h = raw_html or ""
    h = _SCRIPT_RE.sub("", h)
    h = _SELECT_RE.sub('<span class="hv" data-k=""></span>', h)
    h = _TEXTAREA_RE.sub('<span class="hv" data-k=""></span>', h)

    def _input(m):
        tag = m.group(0)
        ids = FIELD_ID_RE.search(tag)
        key = f"{ids.group(1)}-{ids.group(2)}" if ids else ""
        return f'<span class="hv" data-k="{key}"></span>'

    h = _INPUT_RE.sub(_input, h)
    h = _HANDLER_RE.sub("", h)
    h = _JSURL_RE.sub(r'\1="#"', h)
    return h


def _ensure_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS form_cache (
        dataset_key VARCHAR(64) PRIMARY KEY,
        html        TEXT NOT NULL,
        slots       INTEGER NOT NULL DEFAULT 0,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now())""")


def _load_cached(dataset_key: str):
    from . import db
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute("SELECT html FROM form_cache WHERE dataset_key=%s", (dataset_key,))
            row = cur.fetchone()
            return row["html"] if row else None


def _save_cached(dataset_key: str, skeleton: str, slots: int):
    from . import db
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute(
                """INSERT INTO form_cache (dataset_key, html, slots) VALUES (%s,%s,%s)
                   ON CONFLICT (dataset_key) DO UPDATE
                   SET html=EXCLUDED.html, slots=EXCLUDED.slots, updated_at=now()""",
                (dataset_key, skeleton, slots),
            )


def skeleton(report_type: str, force_refresh: bool = False) -> str:
    """The sanitised official form for a report type, cached in memory and Postgres."""
    types = mapping().get("reportTypes", {})
    entry = types.get((report_type or "").upper())
    if not entry:
        raise RuntimeError(f"Unknown report type '{report_type}'")
    key = entry["dataSet"]

    if not force_refresh and key in _SKELETONS:
        return _SKELETONS[key]

    skel = None
    if not force_refresh:
        try:
            skel = _load_cached(key)
        except Exception:
            skel = None

    if skel is None:
        ds_id = mapping()["dataSets"][key]["id"]
        raw = _fetch_form_html(ds_id)
        if not raw:
            raise RuntimeError(
                f"DHIS2 holds no custom entry form for {mapping()['dataSets'][key]['name']}, "
                "so there is no official layout to preview."
            )
        skel = sanitise(raw)
        try:
            _save_cached(key, skel, len(_SLOT_RE.findall(skel)))
        except Exception:
            pass  # cache is an optimisation, never a dependency

    _SKELETONS[key] = skel
    return skel


def reset_cache():
    _SKELETONS.clear()


def refresh_all():
    """Re-fetch every registered form. Returns {report_type: slot count}."""
    out = {}
    for rt in mapping().get("reportTypes", {}):
        try:
            out[rt] = len(_SLOT_RE.findall(skeleton(rt, force_refresh=True)))
        except Exception as exc:
            out[rt] = f"error: {exc}"
    return out


def values_map(compiled_values: list) -> dict:
    """Compiled data values -> {'DE-COC': 'value'} for injection."""
    return {
        f"{v['dataElement']}-{v['categoryOptionCombo']}": str(v.get("value", ""))
        for v in (compiled_values or [])
        if v.get("dataElement") and v.get("categoryOptionCombo")
    }


def imputed_keys(compiled_values: list) -> set:
    """The subset of keys that are zero-fills rather than measurements.

    A measured zero and an imputed zero print the same character, so the
    difference has to be carried separately or the page cannot tell the reader
    which is which — and on a surveillance return that difference is the whole
    point."""
    return {
        f"{v['dataElement']}-{v['categoryOptionCombo']}"
        for v in (compiled_values or [])
        if v.get("imputed") and v.get("dataElement") and v.get("categoryOptionCombo")
    }


PAGE_CSS = """
:root { --deep:#0F5257; --mid:#1B7B7B; --coral:#C2552E; --pale:#E8F1F1;
        --line:#D4E2E2; --ink:#1A1A1A; --grey:#6B7A7A; }
body { margin:0; padding:0 0 40px; background:#fff; color:var(--ink);
       font-family:'Gill Sans MT','Gill Sans',Calibri,'Trebuchet MS',sans-serif; font-size:13px; }
.hdr { background:var(--deep); color:#fff; padding:14px 20px; }
.hdr h1 { margin:0; font-size:17px; font-weight:700; letter-spacing:.2px; }
.hdr .sub { margin-top:3px; font-size:12px; color:#A8CFCF; }
.bar { display:flex; flex-wrap:wrap; gap:18px; align-items:center;
       padding:9px 20px; background:var(--pale); border-bottom:1px solid var(--line);
       font-size:12px; color:var(--deep); }
.bar b { font-weight:700; }
.bar .flag { color:var(--coral); font-weight:700; }
.wrap { padding:16px 20px; }
.hv { display:inline-block; min-width:44px; padding:1px 5px; text-align:right;
      border-bottom:1px solid var(--line); font-variant-numeric:tabular-nums; }
.hv.filled { background:var(--pale); border-bottom:1px solid var(--mid);
             font-weight:700; color:var(--deep); }
/* An imputed zero is shown, but never dressed up as a measurement: no fill,
   no bold, and a muted colour, so a reader scanning the page can see at a
   glance which figures were counted and which mean "none recorded". */
.hv.zero { color:var(--grey); font-weight:400; }
.hv.empty::after { content:'\\00a0'; color:transparent; }
.legend { display:flex; flex-wrap:wrap; gap:14px; align-items:center;
          padding:7px 20px; border-bottom:1px solid var(--line);
          font-size:11.5px; color:var(--grey); }
.legend i { font-style:normal; display:inline-block; min-width:22px;
            text-align:center; padding:1px 5px; margin-right:5px; }
.legend i.k1 { background:var(--pale); color:var(--deep); font-weight:700;
               border-bottom:1px solid var(--mid); }
.legend i.k2 { color:var(--grey); border-bottom:1px solid var(--line); }
.legend i.k3 { border-bottom:1px solid var(--line); }
table { border-collapse:collapse; }
td, th { padding:2px 5px; vertical-align:middle; }
img { max-width:100%; }
"""


def render_document(report_type: str, period: str, period_label: str,
                    values: dict, meta: dict) -> str:
    """A complete, self-contained HTML document for the preview iframe."""
    types = mapping().get("reportTypes", {})
    entry = types.get(report_type.upper(), {})
    ds_key = entry.get("dataSet", "")
    ds = mapping()["dataSets"].get(ds_key, {})

    imputed = set(meta.get("imputed") or ())
    counted = {"measured": 0, "zero": 0}

    def _fill(m):
        key = m.group(1)
        if key and key in values:
            if key in imputed:
                counted["zero"] += 1
                return f'<span class="hv zero">{html_lib.escape(values[key])}</span>'
            counted["measured"] += 1
            return f'<span class="hv filled">{html_lib.escape(values[key])}</span>'
        return '<span class="hv empty"></span>'

    body = _SLOT_RE.sub(_fill, skeleton(report_type))

    if meta.get("report_id"):
        state = (f'<span><b>{counted["measured"]}</b> compiled figures from report '
                 f'#{meta["report_id"]}</span>')
        if counted["zero"]:
            state += f' <span>· <b>{counted["zero"]}</b> shown as zero</span>'
        if meta.get("push_status") and meta["push_status"] != "PENDING":
            state += f' <span>· submission status <b>{html_lib.escape(str(meta["push_status"]))}</b></span>'
        else:
            state += ' <span class="flag">· not yet submitted</span>'
    else:
        state = '<span class="flag">Blank form — no report compiled for this period</span>'

    cov = meta.get("coverage") or {}
    if cov.get("notOurs"):
        legend = (
            '<div class="legend">'
            '<span><i class="k1">42</i>counted from the register</span>'
            '<span><i class="k2">0</i>no cases recorded this period</span>'
            '<span><i class="k3">&nbsp;</i>not compiled here — entered from '
            f'another register</span><span>{cov["notOurs"]} of {cov["cells"]} cells '
            'on this form are filled by other staff, so they are left blank rather '
            'than zeroed.</span></div>'
        )
    else:
        legend = ""

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html_lib.escape(ds.get('name', report_type))}</title>"
        f"<style>{PAGE_CSS}</style></head><body>"
        f"<div class='hdr'><h1>{html_lib.escape(ds.get('name', report_type))}</h1>"
        f"<div class='sub'>{html_lib.escape(mapping()['orgUnit']['name'])}</div></div>"
        f"<div class='bar'><span>Period <b>{html_lib.escape(period)}</b> — "
        f"{html_lib.escape(period_label)}</span>{state}</div>"
        f"{legend}"
        f"<div class='wrap'>{body}</div></body></html>"
    )
