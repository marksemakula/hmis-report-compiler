'use client';
import { useCallback, useEffect, useState } from 'react';
import { IconAlert } from './icons';

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
 */

const SCREENED = '#066fd1';
const NOT_SCREENED = '#d63939';

const LEVELS = [
  { scope: 'facility', label: 'Jinja RRH' },
  { scope: 'region', label: 'Busoga Region' },
  { scope: 'national', label: 'MoH - National' },
];

const nf = (n) => Number(n || 0).toLocaleString('en-GB');

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

export default function TbScreening() {
  const [scope, setScope] = useState('facility');
  // Empty means "whatever the server matched by name". The pickers appear only
  // when 033B offers more than one candidate, so a wrong match is correctable
  // rather than silent.
  const [attEl, setAttEl] = useState('');
  const [scrEl, setScrEl] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [hover, setHover] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const qs = new URLSearchParams({ scope });
      if (attEl) qs.set('attendance', attEl);
      if (scrEl) qs.set('screened', scrEl);
      const r = await fetch(`/api/py/tb-screening?${qs.toString()}`);
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(b?.detail || `Screening figures unavailable (HTTP ${r.status}).`);
      setData(b);
    } catch (e) {
      setData(null);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [scope, attEl, scrEl]);

  useEffect(() => { load(); }, [load]);

  const series = (key, value, set, label) => {
    const matched = data?.candidates?.[key] || [];
    // When the name matcher found nothing, offer every 033B element rather
    // than nothing: the reader knows which line of the form they want, and a
    // regex that failed to recognise a name is no reason to refuse to draw.
    const options = matched.length ? matched : (data?.candidates?.all || []);
    if (options.length < 2 && !data?.needsChoice) return null;
    return (
      <div style={{ marginTop: '.5rem' }}>
        <label htmlFor={`tb-${key}`}>{label}</label>
        <select id={`tb-${key}`} value={value || data?.elements?.[key]?.id || ''}
          onChange={(e) => set(e.target.value)}>
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      </div>
    );
  };

  const picker = (
    <>
      <div>
        <label htmlFor="tb-level">Level</label>
        <select id="tb-level" value={scope} onChange={(e) => setScope(e.target.value)}>
          {LEVELS.map((l) => <option key={l.scope} value={l.scope}>{l.label}</option>)}
        </select>
      </div>
      {series('attendance', attEl, setAttEl, 'Attendance series')}
      {series('screened', scrEl, setScrEl, 'TB screening series')}
    </>
  );

  if (loading && !data) {
    return (
      <>
        {picker}
        <div className="loading-bar" style={{ margin: '1rem 0 .5rem' }} />
        <div className="text-secondary" style={{ fontSize: '.8125rem' }}>Reading DHIS2…</div>
      </>
    );
  }

  if (error) {
    return (
      <>
        {picker}
        <div className="empty" style={{ padding: '1.25rem 0 .5rem' }}>
          <div className="empty-icon"><IconAlert size={28} /></div>
          <div className="empty-subtitle" style={{ marginBottom: '.75rem' }}>{error}</div>
          <button type="button" className="btn secondary sm" onClick={load}>Try again</button>
        </div>
      </>
    );
  }

  if (!data) return null;

  const { attendance, screened, notScreened, rate } = data;
  const nothing = !data.reported || !attendance;
  const S = 168, R = 74, RI = 48, C = S / 2;
  const screenedDeg = nothing ? 0 : (screened / attendance) * 360;

  const slices = [
    { key: 'screened', label: 'Screened for TB', value: screened, colour: SCREENED,
      from: 0, to: screenedDeg },
    { key: 'not', label: 'Not screened', value: notScreened, colour: NOT_SCREENED,
      from: screenedDeg, to: 360 },
  ];

  return (
    <>
      {picker}

      {data.inconsistent && (
        <div className="alert warn" style={{ marginTop: '.75rem' }}>
          More people were recorded as screened than attended over {data.periodLabel}.
          One of the two 033B elements is likely unfiled; the share below is not reliable.
        </div>
      )}

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
      ) : (
        <div className="d-flex items-center gap-4 flex-wrap" style={{ marginTop: '.875rem' }}>
          <svg width={S} height={S} viewBox={`0 0 ${S} ${S}`} style={{ flex: 'none' }} role="img"
            aria-label={`${rate}% of ${nf(attendance)} attendances screened for TB, ${data.periodLabel}`}>
            {slices.map((s) => (
              s.to - s.from <= 0 ? null : (
                <path key={s.key} d={arc(C, C, R, RI, s.from, s.to)} fill={s.colour}
                  stroke="#fff" strokeWidth="2"
                  opacity={hover === null || hover === s.key ? 1 : 0.55}
                  onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover(null)} />
              )
            ))}
            <text x={C} y={C - 2} textAnchor="middle" fontSize="26" fontWeight="700" fill="#111827">
              {rate === null ? '-' : `${Math.round(rate)}%`}
            </text>
            <text x={C} y={C + 18} textAnchor="middle" fontSize="11" fill="#374151">screened</text>
          </svg>

          <div style={{ minWidth: 0, flex: 1 }}>
            {slices.map((s) => (
              <div key={s.key} className="d-flex items-center gap-2"
                style={{ padding: '.3125rem 0', fontSize: '.8125rem' }}
                onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover(null)}>
                <span style={{ width: 10, height: 10, borderRadius: 3, background: s.colour, flex: 'none' }} />
                <span style={{ color: 'var(--tblr-body-color)' }}>{s.label}</span>
                <span className="ms-auto fw-bold" style={{ color: s.colour }}>{nf(s.value)}</span>
              </div>
            ))}
            <div className="d-flex items-center gap-2"
              style={{ padding: '.4375rem 0 0', marginTop: '.25rem', fontSize: '.8125rem',
                borderTop: '1px solid rgba(4,32,69,.1)' }}>
              <span className="fw-medium">Total attendance</span>
              <span className="ms-auto fw-bold">{nf(attendance)}</span>
            </div>
            <div className="stat-foot">
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
