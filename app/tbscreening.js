'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { IconAlert } from './icons';
import useWidth from './usewidth';

/* Attendance split by whether the patient was screened for TB, counted from
 * the start of the year.
 *
 * Both series are HMIS 033B, the weekly return, so the total is the sum of ISO
 * weeks 1 to the current week. Weeks nobody filed contribute nothing rather
 * than a zero, and the card says how many of the elapsed weeks reported, so a
 * thin denominator is visible instead of implied.
 *
 * Drawn as a part-to-whole because that is what it is. "Screened for TB" is a
 * subset of attendance, so a pie of attendance against screened would draw the
 * screened patients twice and its slices would total something that is not a
 * population. Attendance split into screened and not screened is a real whole,
 * and it answers the question the figure is looked at for: what share of the
 * people who came through the door were screened.
 *
 * Blue for screened, red for the gap. The two separate by 23.4 in the worst
 * colour-vision case, and both slices are directly labelled, so the reading
 * never rests on colour alone.
 *
 * The OUTER ring is the age profile of attendance, from 105:01, also cumulative
 * from January. Two things follow from that and are stated on the card rather
 * than left to be inferred:
 *
 *  - 105:01 is monthly and 033B is weekly, so the outer ring covers months 1 to
 *    the current month while the inner covers weeks 1 to the current week.
 *  - They are different returns, so their totals will not agree. Each ring is
 *    therefore its own 100%. The outer ring does NOT subdivide the inner one,
 *    and no angle in one corresponds to an angle in the other.
 *
 * Age bands are ordered, so the outer ring is a sequential ramp - one hue,
 * light to dark, OKLab L 0.905/0.812/0.704/0.573/0.429 - not a categorical set.
 * Teal rather than blue so the darkest band cannot be mistaken for the inner
 * ring's blue; the mid step sits 22.8 from that blue and 15.4 from the red in
 * the worst colour-vision case.
 */

const SCREENED = '#066fd1';
const NOT_SCREENED = '#d63939';
const AGE_RAMP = ['#c9e7e2', '#8fd0c8', '#4fb3a8', '#1d8a80', '#0b5c56'];

const LEVELS = [
  { scope: 'facility', label: 'Jinja RRH' },
  { scope: 'region', label: 'Busoga Region' },
  { scope: 'national', label: 'MoH - National' },
];

const nf = (n) => Number(n || 0).toLocaleString('en-GB');

/** A share as a whole number, without rounding a real slice away to "0%". */
function pct(value, total) {
  if (!total) return '';
  const p = (100 * value) / total;
  if (p > 0 && p < 0.5) return '<1%';
  if (p > 99.5 && p < 100) return '>99%';
  return `${Math.round(p)}%`;
}

/** An SVG arc for one slice of a donut. */
function arc(cx, cy, rOuter, rInner, from, to) {
  // A slice covering the whole circle cannot be drawn as a single arc; two
  // half arcs stand in for it.
  if (to - from >= 359.999) {
    const half = (r, sweep) =>
      `M${cx - r},${cy}A${r},${r} 0 1 ${sweep} ${cx + r},${cy}A${r},${r} 0 1 ${sweep} ${cx - r},${cy}`;
    return `${half(rOuter, 1)}${half(rInner, 0)}`;
  }
  const rad = (d) => ((d - 90) * Math.PI) / 180;
  const p = (r, d) => [cx + r * Math.cos(rad(d)), cy + r * Math.sin(rad(d))];
  const [x1, y1] = p(rOuter, from);
  const [x2, y2] = p(rOuter, to);
  const [x3, y3] = p(rInner, to);
  const [x4, y4] = p(rInner, from);
  const large = to - from > 180 ? 1 : 0;
  return `M${x1},${y1}A${rOuter},${rOuter} 0 ${large} 1 ${x2},${y2}`
    + `L${x3},${y3}A${rInner},${rInner} 0 ${large} 0 ${x4},${y4}Z`;
}

/* How wide a string renders, near enough to decide whether it will be clipped.
 *
 * Text cannot be measured before it is drawn without a canvas, and a canvas is
 * not available during the server render. These are Ubuntu's advance widths in
 * em, rounded up, with a margin on top so that a fallback face - which is what
 * actually paints while the font is still loading - does not overrun a slice
 * this decided was wide enough. */
const CHAR_EM = { ' ': 0.28, ',': 0.28, '.': 0.28, '-': 0.36, '+': 0.6, '%': 0.87, '<': 0.6, '>': 0.6 };
function textWidth(s, size) {
  let em = 0;
  for (const ch of String(s)) {
    if (CHAR_EM[ch] !== undefined) em += CHAR_EM[ch];
    else if (ch >= '0' && ch <= '9') em += 0.556;
    else if (ch >= 'A' && ch <= 'Z') em += 0.68;
    else em += 0.53;
  }
  return em * size * 1.06;
}

/* Whether a block of horizontal text fits inside one slice.
 *
 * Locally a slice is a rectangle: as long along the tangent as its shortest
 * arc, which is the one at the inner edge of the band, and as deep along the
 * radius as the band itself. A horizontal box sitting at mid-angle phi
 * projects onto those two axes by the usual support function, which is the two
 * inequalities below. Padding comes off first, because a label touching the
 * edge of its own slice reads as a label for the next one.
 *
 * The tangential room is also capped by the longest straight line that stays
 * inside the band, since a chord leaves a curved ring well before the arc
 * beneath it runs out. That cap only binds on slices past a half turn, but
 * those are exactly the ones the rectangle model would otherwise flatter.
 */
function fits(w, h, from, to, ri, ro) {
  const phi = (((from + to) / 2) * Math.PI) / 180;
  const c = Math.abs(Math.cos(phi));
  const s = Math.abs(Math.sin(phi));
  const chord = 2 * Math.sqrt(Math.max(0, ro * ro - ri * ri));
  const along = Math.min(ri * (((to - from) * Math.PI) / 180), chord) - 10;
  const deep = ro - ri - 8;
  if (along <= 0 || deep <= 0) return false;
  return w * c + h * s <= along && w * s + h * c <= deep;
}

/* The most a slice can say without being clipped, or null.
 *
 * Candidates are tried longest first. A label that does not fit is never
 * shrunk to make it fit: 8px type in a chart is not a label, it is a texture.
 * It falls back to a shorter form and then to nothing, which is why the legend
 * below still carries every slice and every slice keeps its tooltip. */
function labelFor(candidates, from, to, ri, ro) {
  for (const lines of candidates) {
    const w = Math.max(...lines.map((l) => textWidth(l.text, l.size)));
    const h = lines.reduce((a, l) => a + l.size * 1.15, 0);
    if (fits(w, h, from, to, ri, ro)) return lines;
  }
  return null;
}

/* Black or white on a given fill, whichever the eye can actually read.
 *
 * The age ramp runs from very pale to very dark, so no one ink works across
 * it. WCAG relative luminance decides per band rather than a guess at where
 * the ramp turns dark. */
function inkOn(hex) {
  const ch = (i) => {
    const v = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const L = 0.2126 * ch(0) + 0.7152 * ch(1) + 0.0722 * ch(2);
  return (L + 0.05) / 0.05 > 1.05 / (L + 0.05) ? '#000000' : '#ffffff';
}

/** One or two lines of centred text, laid out around a point. */
function Label({ x, y, lines, fill }) {
  const h = lines.reduce((a, l) => a + l.size * 1.15, 0);
  let top = y - h / 2;
  return (
    <g pointerEvents="none">
      {lines.map((l, i) => {
        const baseline = top + l.size * 0.9;
        top += l.size * 1.15;
        return (
          <text key={i} x={x} y={baseline} textAnchor="middle" fill={fill}
            fontSize={l.size} fontWeight={l.weight || 400}>
            {l.text}
          </text>
        );
      })}
    </g>
  );
}

/* Age bands come back named the way the form names them. A slice has room for
 * a few characters, not for "29 days to 4 years", so days and years are
 * abbreviated; anything this does not recognise keeps its own name and simply
 * fails the fit test, which is the right outcome. */
function shortBand(band, label) {
  const s = String(band || '').replace(/Dys/gi, 'd').replace(/Yrs?/gi, 'y').replace(/\s+/g, '');
  return s && s.length <= 8 ? s : label;
}

/** The query a fetch is made from: what has actually been asked for. */
const asQuery = (q) => {
  const p = new URLSearchParams({ scope: q.scope });
  if (q.attendance.length) p.set('attendance', q.attendance.join(','));
  if (q.screened) p.set('screened', q.screened);
  return p.toString();
};

const START = { scope: 'facility', attendance: [], screened: '' };

export default function TbScreening() {
  /* Two copies of the filter state. `draft` is what the controls show and
     `applied` is what the chart was drawn from; only pressing Load moves one
     to the other. Firing a request on every change of a select means a reader
     changing two filters watches the chart redraw from a combination they
     never asked for, and pays for a DHIS2 query to see it. */
  const [draft, setDraft] = useState(START);
  const [applied, setApplied] = useState(START);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [hover, setHover] = useState(null);
  // The series pickers are folded away by default: they are a correction, not
  // a filter, and on most days nobody touches them.
  const [openSeries, setOpenSeries] = useState(false);
  const wrap = useRef(null);
  const width = useWidth(wrap, 320);

  const query = asQuery(applied);
  const dirty = query !== asQuery(draft);

  const load = useCallback(async (qs) => {
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`/api/py/tb-screening?${qs}`);
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(b?.detail || `Screening figures unavailable (HTTP ${r.status}).`);
      setData(b);
    } catch (e) {
      setData(null);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(query); }, [load, query]);

  const set = (patch) => setDraft((d) => ({ ...d, ...patch }));

  /* The denominator takes more than one line, because on this form the total
     OPD attendance is more than one line. Checkboxes rather than a select for
     that reason: a select can only say one of them. */
  const denominator = () => {
    const matched = data?.candidates?.attendance || [];
    const options = matched.length ? matched : (data?.candidates?.all || []);
    if (!options.length) return null;
    const current = draft.attendance.length
      ? draft.attendance
      : (data?.elements?.attendance || []).map((e) => e.id);
    return (
      <fieldset style={{ border: 0, padding: 0, margin: '0 0 .5rem', minWidth: 0 }}>
        <legend className="form-label sm" style={{ padding: 0 }}>
          Denominator · total OPD attendance
        </legend>
        <div className="text-secondary" style={{ fontSize: '.6875rem', marginBottom: '.25rem' }}>
          Tick every line the total is made of. They are added together.
        </div>
        {options.map((o) => (
          <label key={o.id} className="d-flex items-center gap-2"
            style={{ fontSize: '.75rem', fontWeight: 400, padding: '.125rem 0',
              marginBottom: 0, cursor: 'pointer' }}>
            <input type="checkbox" checked={current.includes(o.id)}
              onChange={(e) => set({
                attendance: e.target.checked
                  ? [...current, o.id]
                  : current.filter((id) => id !== o.id),
              })} />
            <span>{o.label}</span>
          </label>
        ))}
      </fieldset>
    );
  };

  const numerator = () => {
    const matched = data?.candidates?.screened || [];
    const options = matched.length ? matched : (data?.candidates?.all || []);
    if (!options.length) return null;
    return (
      <div style={{ minWidth: 0 }}>
        <label className="form-label sm" htmlFor="tb-screened">Numerator · screened for TB</label>
        <select id="tb-screened" className="sm" value={draft.screened || data?.elements?.screened?.id || ''}
          onChange={(e) => set({ screened: e.target.value })}>
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      </div>
    );
  };

  /* One compact line of controls. The card is a chart, so the chart gets the
     room: the level select sizes to its content instead of the card, and the
     two series pickers live behind a toggle. */
  const picker = (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: '.5rem',
      flexWrap: 'wrap', marginBottom: '.25rem' }}>
      <div style={{ minWidth: 0 }}>
        <label className="form-label sm" htmlFor="tb-level">Level</label>
        <select id="tb-level" className="sm" style={{ width: 'auto', minWidth: '9.5rem' }}
          value={draft.scope} onChange={(e) => set({ scope: e.target.value })}>
          {LEVELS.map((l) => <option key={l.scope} value={l.scope}>{l.label}</option>)}
        </select>
      </div>
      <button type="button" id="tb-load" className={`btn sm${dirty ? '' : ' secondary'}`}
        disabled={loading || !dirty} onClick={() => setApplied(draft)}>
        {loading ? 'Loading…' : 'Load'}
      </button>
      <button type="button" id="tb-series" className="btn ghost sm ms-auto"
        aria-expanded={openSeries} onClick={() => setOpenSeries((v) => !v)}>
        {openSeries ? 'Hide series' : 'Series'}
      </button>
    </div>
  );

  const seriesPanel = (openSeries || data?.needsChoice || data?.inconsistent) ? (
    <div style={{ padding: '.625rem .75rem', marginBottom: '.75rem',
      border: '1px solid rgba(4,32,69,.12)', borderRadius: 'var(--tblr-border-radius)' }}>
      {denominator()}
      {numerator()}
      {dirty && (
        <div className="text-secondary" style={{ fontSize: '.6875rem', marginTop: '.5rem' }}>
          Press Load to draw the chart from these.
        </div>
      )}
    </div>
  ) : null;

  /* Every branch renders through the same wrapper, and the wrapper carries the
     ref. A ref that only mounts on the branch holding the chart is a ref that
     is null when the observer goes looking for it - the effect runs once, on a
     first render where the component is still loading - so the chart keeps the
     fallback width for the life of the page. */
  const shell = (body) => <div ref={wrap}>{picker}{seriesPanel}{body}</div>;

  if (loading && !data) {
    return shell(
      <>
        <div className="loading-bar" style={{ margin: '1rem 0 .5rem' }} />
        <div className="text-secondary" style={{ fontSize: '.8125rem' }}>Reading DHIS2…</div>
      </>
    );
  }

  if (error) {
    return shell(
      <div className="empty" style={{ padding: '1.25rem 0 .5rem' }}>
        <div className="empty-icon"><IconAlert size={28} /></div>
        <div className="empty-subtitle" style={{ marginBottom: '.75rem' }}>{error}</div>
        <button type="button" className="btn secondary sm"
          onClick={() => load(query)}>Try again</button>
      </div>
    );
  }

  if (!data) return shell(null);

  const { attendance, screened, notScreened, rate } = data;
  const nothing = !data.reported || !attendance;
  /* A numerator larger than its denominator is not a share, and a ring drawn
     from it is not a part-to-whole: it is a full circle of blue with the red
     silently gone, over a percentage above 100. So the ring is refused and the
     two counts are shown as what they are, next to the control that fixes it. */
  const impossible = data.inconsistent;
  const age = data.ageProfile || { available: false, bands: [], total: 0 };
  const ageTotal = age.bands.reduce((a, b) => a + b.value, 0) + (age.unclassified || 0);
  const hasAge = age.available && ageTotal > 0;

  /* The chart takes the width the card gives it rather than a fixed 208px, so
     it is as large as the column allows and shrinks instead of overflowing.
     The cap is there because a donut past about 420px stops reading as one
     shape; the floor keeps the arcs drawable on a phone. */
  const box = Math.max(200, Math.min(width || 320, 420));
  const C = box / 2;
  const R = C - 1;

  /* The legend goes beside the donut when what is left over can hold it, and
     under it when it cannot. Beside is worth reaching for: it halves the
     height of the card, which is what keeps this from towering over the
     counters it shares a row with. 13rem is where the age rows stop wrapping
     their band names onto a second line. */
  const LEGEND_MIN = 208;
  const beside = width - box - 24 >= LEGEND_MIN;

  /* One ring or two. With no 105:01 age profile there is nothing to put on the
     outside, and holding the inner ring at its two-ring radius would centre a
     small donut in a large empty box. */
  const OUTER_R = R;
  const OUTER_RI = R * 0.735;
  const INNER_R = hasAge ? R * 0.655 : R;
  const INNER_RI = hasAge ? R * 0.385 : R * 0.56;

  /* Type in the hole scales with the hole. Type on a slice does not: it keeps
     its stated size at every chart size, which is the point of matching the
     viewBox to the measured width. A chart too small to hold an 11px label
     therefore drops the label rather than shrinking it into a texture. */
  const bigSize = Math.round(INNER_RI * 0.52);
  const subSize = Math.max(10, Math.round(INNER_RI * 0.17));
  const subRoom = 2 * Math.sqrt(Math.max(0, INNER_RI * INNER_RI - (subSize * 1.6) ** 2));
  const subText = textWidth('screened for TB', subSize) <= subRoom ? 'screened for TB' : 'screened';

  /* Clamped, and not only because the impossible case is caught above. An arc
     of 2747 degrees is not a slice: `arc` treats anything past a full turn as
     the whole circle, so the ring comes out solid blue with the red slice
     silently absent and nothing on screen says the number was wrong. A ring
     that cannot exceed a full turn cannot tell that lie. */
  const screenedDeg = nothing ? 0
    : Math.max(0, Math.min(360, (screened / attendance) * 360));

  const slices = [
    { key: 'screened', label: 'Screened for TB', short: 'Screened', value: screened,
      colour: SCREENED, from: 0, to: screenedDeg },
    { key: 'not', label: 'Not screened', short: 'Not screened', value: notScreened,
      colour: NOT_SCREENED, from: screenedDeg, to: 360 },
  ];

  let cursor = 0;
  const ageSlices = (hasAge ? age.bands : []).map((b, i) => {
    const from = cursor;
    cursor += (b.value / ageTotal) * 360;
    return { key: b.band, label: b.label, short: shortBand(b.band, b.label), value: b.value,
             colour: AGE_RAMP[i % AGE_RAMP.length], from, to: cursor };
  });

  /* The white gap between slices is a stroke, so it eats into both of them.
     At two pixels that is nothing on a slice fifty pixels wide and everything
     on a slice four pixels wide, where it removes the slice: a screening rate
     of one percent then has no blue in the ring at all. So the divider never
     takes more than a third of the slice it borders. */
  const strokeFor = (from, to, ro) =>
    Math.max(0.4, Math.min(2, (ro * ((to - from) * Math.PI)) / 180 / 3));

  /** The point at radius r on a slice's mid-angle, where its label sits. */
  const at = (r, from, to) => {
    const d = (((from + to) / 2 - 90) * Math.PI) / 180;
    return [C + r * Math.cos(d), C + r * Math.sin(d)];
  };

  return shell(
    <>
      {data.needsChoice ? (
        <div className="alert warn" style={{ marginTop: '.75rem' }}>
          {data.candidates.cached} HMIS 033B elements are cached, but none is named
          recognisably as
          {!data.matched.attendance && !data.matched.screened
            ? ' total attendance or TB screening'
            : !data.matched.attendance ? ' total attendance' : ' TB screening'}.
          Choose the right line of the form above and the figure will be drawn from it.
        </div>
      ) : nothing ? (
        <div className="empty" style={{ padding: '1.5rem 0 .5rem' }}>
          <div className="empty-subtitle">
            No 033B attendance was reported for {data.orgUnit.name} over {data.periodLabel}.
          </div>
        </div>
      ) : impossible ? (
        <div>
          <div className="alert error">
            <strong>{nf(screened)} screened out of {nf(attendance)} attendances</strong> is
            {' '}{rate === null ? 'more than everyone' : `${Math.round(rate)}%`}, so this is
            not a share and it is not drawn. The numerator is right and the denominator is
            short: total OPD attendance is more than one line of the form, and only
            {' '}{(data.elements.attendance || []).length === 1 ? 'one is' : 'some are'}
            {' '}counted here.
          </div>
          <div className="datagrid" style={{ gap: '.75rem 1.5rem', marginTop: '.75rem' }}>
            <div>
              <div className="page-pretitle">Numerator · screened for TB</div>
              <div className="stat-value is-primary" style={{ fontSize: '1.5rem' }}>{nf(screened)}</div>
              <div className="stat-foot">{data.elements.screened?.label}</div>
            </div>
            <div>
              <div className="page-pretitle">Denominator · counted so far</div>
              <div className="stat-value is-danger" style={{ fontSize: '1.5rem' }}>{nf(attendance)}</div>
              <div className="stat-foot">
                {(data.elements.attendance || []).map((e) => e.label).join(' + ') || 'nothing'}
              </div>
            </div>
          </div>
          <div className="stat-foot">
            Open Series above and tick every line total OPD attendance is made of, then
            press Load. {data.periodLabel} · {data.orgUnit.name}
          </div>
        </div>
      ) : (
        <div style={{ marginTop: '.875rem', display: 'flex', gap: '1.5rem',
          alignItems: beside ? 'center' : 'stretch',
          flexDirection: beside ? 'row' : 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'center', flex: 'none' }}>
            <svg width={box} height={box} viewBox={`0 0 ${box} ${box}`} role="img"
              aria-label={`${rate}% of ${nf(attendance)} attendances screened for TB over ${data.periodLabel}, with the 105:01 age profile of attendance on the outer ring`}>
              {ageSlices.map((a) => {
                if (a.to - a.from <= 0) return null;
                const share = pct(a.value, ageTotal);
                const lines = labelFor([
                  [{ text: a.short, size: 11 }, { text: share, size: 13, weight: 700 }],
                  [{ text: share, size: 12, weight: 700 }],
                ], a.from, a.to, OUTER_RI, OUTER_R);
                const [lx, ly] = at((OUTER_R + OUTER_RI) / 2, a.from, a.to);
                return (
                  <g key={`age-${a.key}`}
                    opacity={hover === null || hover === `age-${a.key}` ? 1 : 0.5}
                    onMouseEnter={() => setHover(`age-${a.key}`)}
                    onMouseLeave={() => setHover(null)}>
                    <title>{`${a.label}: ${nf(a.value)} (${share} of 105:01 attendance)`}</title>
                    <path d={arc(C, C, OUTER_R, OUTER_RI, a.from, a.to)} fill={a.colour}
                      stroke="#fff" strokeWidth={strokeFor(a.from, a.to, OUTER_R)} />
                    {lines && <Label x={lx} y={ly} lines={lines} fill={inkOn(a.colour)} />}
                  </g>
                );
              })}

              {slices.map((s) => {
                if (s.to - s.from <= 0) return null;
                const share = pct(s.value, attendance);
                /* The name is worth a whole line when the slice can hold one.
                   When it cannot, the share is the next best thing: it is the
                   line the centre figure already names, so a reader who sees
                   25% in the hole knows without a legend which arc is which. */
                const lines = labelFor([
                  [{ text: s.short, size: 11 }, { text: nf(s.value), size: 14, weight: 700 }],
                  [{ text: nf(s.value), size: 13, weight: 700 }, { text: share, size: 11 }],
                  [{ text: nf(s.value), size: 13, weight: 700 }],
                  [{ text: share, size: 12, weight: 700 }],
                ], s.from, s.to, INNER_RI, INNER_R);
                const [lx, ly] = at((INNER_R + INNER_RI) / 2, s.from, s.to);
                return (
                  <g key={s.key} opacity={hover === null || hover === s.key ? 1 : 0.5}
                    onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover(null)}>
                    <title>{`${s.label}: ${nf(s.value)} (${share} of attendance)`}</title>
                    <path d={arc(C, C, INNER_R, INNER_RI, s.from, s.to)} fill={s.colour}
                      stroke="#fff" strokeWidth={strokeFor(s.from, s.to, INNER_R)} />
                    {lines && <Label x={lx} y={ly} lines={lines} fill={inkOn(s.colour)} />}
                  </g>
                );
              })}

              <g pointerEvents="none">
                <text x={C} y={C + bigSize * 0.2} textAnchor="middle" fontSize={bigSize}
                  fontWeight="700" fill="#111827">
                  {rate === null ? '-' : `${Math.round(rate)}%`}
                </text>
                <text x={C} y={C + bigSize * 0.2 + subSize * 1.55} textAnchor="middle"
                  fontSize={subSize} fill="#374151">{subText}</text>
              </g>
            </svg>
          </div>

          {/* The legend still carries every slice. Labels on the chart are the
              fast read; the legend is the exact one, and it is the only place a
              slice too thin to label ever appears. */}
          <div style={{ minWidth: 0, flex: 1, display: 'grid', gap: '.875rem 1.5rem',
            gridTemplateColumns: beside ? '1fr' : 'repeat(auto-fit, minmax(11.5rem, 1fr))' }}>
            <div>
              {slices.map((s) => (
                <div key={s.key} className="d-flex items-center gap-2"
                  style={{ padding: '.3125rem 0', fontSize: '.8125rem' }}
                  onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover(null)}>
                  <span style={{ width: 10, height: 10, borderRadius: 3, background: s.colour, flex: 'none' }} />
                  <span style={{ color: 'var(--tblr-body-color)', minWidth: 0, flex: 1 }}>{s.label}</span>
                  <span className="fw-bold" style={{ color: s.colour, flex: 'none',
                    paddingLeft: '.75rem', whiteSpace: 'nowrap' }}>{nf(s.value)}</span>
                </div>
              ))}
              <div className="d-flex items-center gap-2"
                style={{ padding: '.4375rem 0 0', marginTop: '.25rem', fontSize: '.8125rem',
                  borderTop: '1px solid rgba(4,32,69,.1)' }}>
                <span className="fw-medium" style={{ minWidth: 0, flex: 1 }}>Total attendance</span>
                <span className="fw-bold" style={{ flex: 'none', paddingLeft: '.75rem',
                  whiteSpace: 'nowrap' }}>{nf(attendance)}</span>
              </div>
            </div>

            {hasAge && (
              <div>
                <div className="page-pretitle" style={{ marginBottom: '.25rem' }}>
                  Attendance by age · 105:01 · {age.periodLabel}
                </div>
                {ageSlices.map((a) => (
                  <div key={a.key} className="d-flex items-center gap-2"
                    style={{ padding: '.1875rem 0', fontSize: '.75rem' }}
                    onMouseEnter={() => setHover(`age-${a.key}`)} onMouseLeave={() => setHover(null)}>
                    <span style={{ width: 10, height: 10, borderRadius: 3,
                      background: a.colour, flex: 'none' }} />
                    <span style={{ color: 'var(--tblr-body-color)', minWidth: 0, flex: 1 }}>{a.label}</span>
                    <span className="fw-medium" style={{ flex: 'none', paddingLeft: '.75rem',
                      whiteSpace: 'nowrap' }}>{nf(a.value)}</span>
                  </div>
                ))}
                {age.unclassified > 0 && (
                  <div className="stat-foot">
                    {nf(age.unclassified)} in a disaggregation this build does not recognise
                  </div>
                )}
                {/* The two rings are different returns, so their totals differ.
                    Saying it beats letting a reader infer a subdivision that
                    does not exist. */}
                <div className="stat-foot">
                  Outer ring totals {nf(ageTotal)} from 105:01; the inner ring is 033B.
                  Two returns, so the totals differ.
                </div>
              </div>
            )}

            <div className="stat-foot" style={{ gridColumn: '1 / -1' }}>
              {data.periodLabel} · {data.orgUnit.name}
              {data.weeksReported < data.weeksElapsed && (
                <> · <span className="fw-medium" style={{ color: 'var(--tblr-danger)' }}>
                  {data.weeksReported} of {data.weeksElapsed} weeks reported
                </span></>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
