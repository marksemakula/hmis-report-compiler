'use client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import useWidth from './usewidth';
import { IconAlert } from './icons';

/* The malaria channel.
 *
 * For each ISO week, the same week's case counts from several previous years
 * give a set of percentiles; this year's cases are then plotted against them.
 * Above the 75th percentile is an alert, above the 85th an epidemic - the two
 * thresholds UNIPH's policy brief recommends, in preference to the
 * mean-plus-two-standard-deviations method, which assumes a normal
 * distribution weekly case counts do not have.
 *
 * On colour: this is one of the few charts where green-amber-red is right.
 * Elsewhere in this dashboard that ramp is avoided because green and red
 * separate by only ~8 in deuteranopia. Here severity is also carried by
 * vertical position - the bands are stacked in a fixed order, low to high -
 * and by the labels on them, so colour is the third channel rather than the
 * only one. The line that matters is drawn in ink, not in a band colour.
 */

/* The channel has two walls, and both are now drawn.
 *
 * The upper limit is the 75th percentile of the same week in the baseline
 * years: Uganda's own evaluation of outbreak-detection methods (Malaria
 * Journal, 2024) compared it against mean+2SD and C-SUM on five years of DHIS2
 * data and recommended it for detection everywhere. The epidemic line at the
 * 85th follows UNIPH's policy brief.
 *
 * The lower limit is the 25th percentile, the mirror of the upper. A week below
 * it is not an epidemic signal and is not coloured like one; it is drawn
 * because a week far below every previous year is a fact about the data worth
 * seeing, and at this hospital it has more often meant a return filed short
 * than malaria receding.
 */
const BANDS = [
  { key: 'low', label: 'Below the expected channel', fill: 'rgba(4,32,69,.06)' },
  { key: 'normal', label: 'Expected (25th-75th percentile)', fill: 'rgba(47,179,68,.16)' },
  { key: 'alert', label: 'Alert (>75th percentile)', fill: 'rgba(245,159,0,.20)' },
  { key: 'epidemic', label: 'Epidemic (>85th percentile)', fill: 'rgba(214,57,57,.16)' },
];

const LIMIT_LINES = [
  { key: 'alert', label: 'Upper limit (75th percentile)', stroke: '#f59f00', dash: null },
  { key: 'low', label: 'Lower limit (25th percentile)', stroke: '#4263eb', dash: '6 3' },
];

const STATUS = {
  normal: { badge: 'ok', word: 'Within the expected channel' },
  alert: { badge: 'warn', word: 'Above the alert threshold' },
  epidemic: { badge: 'bad', word: 'Above the epidemic threshold' },
  low: { badge: 'muted', word: 'Below the lower limit' },
  unknown: { badge: 'muted', word: 'Not enough data to classify' },
};

const nf = (n) => (n === null || n === undefined
  ? 'not reported'
  : Math.round(Number(n)).toLocaleString('en-GB'));

/** A round step, so the axis reads 0 / 250 / 500 rather than 0 / 188 / 375. */
function niceStep(rough) {
  if (!(rough > 0)) return 1;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const n = rough / mag;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag;
}

function Channel({ data }) {
  const [hover, setHover] = useState(null);
  const box = useRef(null);
  const W = useWidth(box);

  const H = 300;
  const padL = 46, padR = 12, padT = 12, padB = 30;
  const plotW = Math.max(80, W - padL - padR);
  const plotH = H - padT - padB;

  const weeks = data.weeks || [];
  const peak = Math.max(
    1,
    ...weeks.map((w) => Math.max(w.current ?? 0, w.epidemic ?? 0)),
  );
  const step = niceStep((peak * 1.05) / 4);
  const top = Math.ceil((peak * 1.05) / step) * step;
  const ticks = [];
  for (let v = 0; v <= top + 1e-9; v += step) ticks.push(v);

  const xOf = (i) => padL + (plotW * i) / Math.max(weeks.length - 1, 1);
  const yOf = (v) => padT + plotH - (Math.max(0, Math.min(top, v)) / top) * plotH;

  /* Each band is an area between two series. Weeks with no baseline break the
     band rather than being drawn through as zero, so a gap in the history
     reads as a gap. */
  const areaPath = (lower, upper) => {
    const segs = [];
    let cur = [];
    weeks.forEach((w, i) => {
      const lo = lower(w);
      const up = upper(w);
      if (lo === null || lo === undefined || up === null || up === undefined) {
        if (cur.length > 1) segs.push(cur);
        cur = [];
        return;
      }
      cur.push([xOf(i), yOf(lo), yOf(up)]);
    });
    if (cur.length > 1) segs.push(cur);
    return segs.map((seg) => {
      const upPart = seg.map(([x, , u], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${u.toFixed(1)}`).join('');
      const loPart = [...seg].reverse().map(([x, l]) => `L${x.toFixed(1)},${l.toFixed(1)}`).join('');
      return `${upPart}${loPart}Z`;
    }).join('');
  };

  const linePath = (get) => {
    let d = '';
    let pen = false;
    weeks.forEach((w, i) => {
      const v = get(w);
      if (v === null || v === undefined) { pen = false; return; }
      d += `${pen ? 'L' : 'M'}${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };

  const active = hover === null ? null : weeks[hover];
  const st = STATUS[data.status] || STATUS.unknown;

  return (
    <div ref={box} style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}
        style={{ width: '100%', height: `${H}px`, display: 'block' }} role="img"
        aria-label={`Weekly malaria cases for ${data.orgUnit?.name} in ${data.year}, against percentile bands from ${data.baselineYears?.join(', ')}`}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={padL} x2={W - padR} y1={yOf(v)} y2={yOf(v)} stroke="#e5e7eb" strokeWidth="1" />
            <text x={padL - 8} y={yOf(v) + 4} textAnchor="end" fontSize="11" fill="#6b7280">
              {v >= 1000 ? `${Math.round(v / 1000)}k` : Math.round(v)}
            </text>
          </g>
        ))}

        <path d={areaPath(() => 0, (w) => w.low)} fill={BANDS[0].fill} />
        <path d={areaPath((w) => w.low, (w) => w.alert)} fill={BANDS[1].fill} />
        <path d={areaPath((w) => w.alert, (w) => w.epidemic)} fill={BANDS[2].fill} />
        <path d={areaPath((w) => w.epidemic, () => top)} fill={BANDS[3].fill} />

        <path d={linePath((w) => w.median)} fill="none" stroke="#6b7280"
          strokeWidth="1.5" strokeDasharray="4 3" />
        {/* The two walls of the channel, drawn rather than left as the edge of
            a shaded area: a limit a reader can point at is the thing this chart
            is consulted for, and a band edge is not pointable. */}
        <path d={linePath((w) => w.low)} fill="none" stroke="#4263eb"
          strokeWidth="1.5" strokeDasharray="6 3" />
        <path d={linePath((w) => w.alert)} fill="none" stroke="#f59f00" strokeWidth="1.75" />
        <path d={linePath((w) => w.epidemic)} fill="none" stroke="#d63939" strokeWidth="1.5" />
        <path d={linePath((w) => w.current)} fill="none" stroke="#1f2937"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

        {weeks.map((w, i) => (w.current === null || w.current === undefined ? null : (
          <circle key={w.week} cx={xOf(i)} cy={yOf(w.current)} r={hover === i ? 4.5 : 3}
            fill={w.epidemic !== null && w.current > w.epidemic ? '#d63939' : '#1f2937'}
            stroke="#fff" strokeWidth="1.5" />
        )))}

        {weeks.map((w, i) => (
          <g key={`x${w.week}`}>
            {(w.week === 1 || w.week % 4 === 0) && (
              <text x={xOf(i)} y={H - 10} textAnchor="middle" fontSize="11" fill="#6b7280">{w.week}</text>
            )}
            <rect x={xOf(i) - plotW / Math.max(weeks.length - 1, 1) / 2} y={padT}
              width={plotW / Math.max(weeks.length - 1, 1)} height={plotH} fill="transparent"
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
          </g>
        ))}
      </svg>

      {active && (() => {
        const pctX = (xOf(hover) / W) * 100;
        const shift = pctX > 70 ? 'translateX(-100%)' : pctX < 20 ? 'translateX(0)' : 'translateX(-50%)';
        return (
          <div style={{
            position: 'absolute', top: 0, left: `${pctX}%`, transform: shift,
            pointerEvents: 'none', background: '#fff', border: '1px solid rgba(4,32,69,.1)',
            borderRadius: 6, boxShadow: '0 16px 24px 2px rgba(0,0,0,.07)',
            padding: '.5rem .625rem', fontSize: '.75rem', whiteSpace: 'nowrap', zIndex: 2,
          }}>
            <div className="fw-bold" style={{ marginBottom: '.25rem' }}>
              Week {active.week}, {data.year}
            </div>
            {[
              ['This year', active.current],
              ['Epidemic threshold', active.epidemic],
              ['Upper limit (75th)', active.alert],
              [`Median of ${active.n} year${active.n === 1 ? '' : 's'}`, active.median],
              ['Lower limit (25th)', active.low],
            ].map(([label, value]) => (
              <div className="d-flex items-center gap-2" key={label}>
                <span className="text-secondary">{label}</span>
                <span className="ms-auto fw-medium" style={{ paddingLeft: '1rem' }}>{nf(value)}</span>
              </div>
            ))}
            {/* The extremes are reported but not drawn: a line through the
                highest of five years is a line through five different years,
                and it reads as a threshold when it is only a record. */}
            {active.min !== null && active.min !== undefined && (
              <div className="d-flex items-center gap-2">
                <span className="text-secondary">Seen in this week before</span>
                <span className="ms-auto fw-medium" style={{ paddingLeft: '1rem' }}>
                  {nf(active.min)} to {nf(active.max)}
                </span>
              </div>
            )}
          </div>
        );
      })()}

      <div className="d-flex gap-4 items-center flex-wrap" style={{ marginTop: '.75rem', fontSize: '.75rem' }}>
        {BANDS.map((b) => (
          <span key={b.key} className="d-flex items-center gap-2">
            <span style={{ width: 12, height: 12, borderRadius: 3, background: b.fill,
              boxShadow: 'inset 0 0 0 1px rgba(4,32,69,.12)', flex: 'none' }} />
            <span className="text-secondary">{b.label}</span>
          </span>
        ))}
        {LIMIT_LINES.map((l) => (
          <span key={l.key} className="d-flex items-center gap-2">
            <span style={{ width: 14, height: 0, flex: 'none',
              borderTop: `2px ${l.dash ? 'dashed' : 'solid'} ${l.stroke}` }} />
            <span className="text-secondary">{l.label}</span>
          </span>
        ))}
        <span className="d-flex items-center gap-2">
          <span style={{ width: 14, height: 2, background: '#1f2937', flex: 'none' }} />
          <span className="text-secondary">{data.year} cases</span>
        </span>
        <span className="d-flex items-center gap-2">
          <span style={{ width: 14, height: 0, borderTop: '1.5px dashed #6b7280', flex: 'none' }} />
          <span className="text-secondary">Median of {data.baselineYears?.length} previous years</span>
        </span>
        <span className={`badge ${st.badge} ms-auto`}>{st.word}</span>
      </div>
    </div>
  );
}

export default function MalariaChannel({ scope: initialScope = 'facility' }) {
  const [data, setData] = useState(null);
  const [element, setElement] = useState('');
  const [baseline, setBaseline] = useState(5);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  /* The chart opens on this hospital, which is the question asked of it most
     days, and the other three answers are one control away: the region, the
     country, and any single facility in Busoga. `ou` is only set for that last
     case and takes precedence over the scope on the server. */
  const [scope, setScope] = useState(initialScope);
  const [ou, setOu] = useState('');
  const [scopeList, setScopeList] = useState([]);
  const [facilities, setFacilities] = useState([]);
  const [facilityText, setFacilityText] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const qs = new URLSearchParams({
        scope: scope === 'other' ? 'facility' : scope,
        baseline: String(baseline),
      });
      if (scope === 'other' && ou) qs.set('ou', ou);
      if (element) qs.set('element', element);
      const r = await fetch(`/api/py/malaria/channel?${qs.toString()}`);
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(b?.detail || `The channel could not be built (HTTP ${r.status}).`);
      setData(b);
      if (!element && b?.element?.id) setElement(b.element.id);
    } catch (e) {
      setData(null);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [scope, ou, element, baseline]);

  /* Do not fetch a facility-scoped channel with no facility chosen yet: it
     would draw this hospital again under the label "another facility", which
     is worse than an empty control. */
  useEffect(() => {
    if (scope === 'other' && !ou) return;
    load();
  }, [load, scope, ou]);

  /* The three standing scopes, named by the server so the region reads
     "Busoga" rather than a word this file guessed. */
  useEffect(() => {
    let live = true;
    fetch('/api/py/scopes')
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => { if (live && b?.scopes) setScopeList(b.scopes); })
      .catch(() => {});
    return () => { live = false; };
  }, []);

  /* Six hundred names, fetched once and only when someone actually asks for
     another facility. */
  useEffect(() => {
    if (scope !== 'other' || facilities.length) return undefined;
    let live = true;
    fetch('/api/py/malaria/facilities')
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => { if (live && b?.facilities) setFacilities(b.facilities); })
      .catch(() => {});
    return () => { live = false; };
  }, [scope, facilities.length]);

  const pickFacility = (text) => {
    setFacilityText(text);
    const hit = facilities.find((f) => f.name.toLowerCase() === text.trim().toLowerCase());
    setOu(hit ? hit.id : '');
  };

  const years = useMemo(() => [3, 5, 7, 10], []);

  if (loading && !data) {
    return (
      <>
        <div className="loading-bar" style={{ marginBottom: '1rem' }} />
        <div className="text-secondary">
          Reading five years of weekly surveillance from DHIS2…
        </div>
      </>
    );
  }

  if (error) {
    return (
      <div className="empty">
        <div className="empty-icon"><IconAlert size={40} /></div>
        <div className="empty-title">The malaria channel could not be drawn</div>
        <div className="empty-subtitle" style={{ marginBottom: '1rem' }}>{error}</div>
        <button type="button" className="btn secondary" onClick={load}>Try again</button>
      </div>
    );
  }

  if (!data) return null;

  return (
    <>
      <div className="map-filters" style={{ marginBottom: '1rem' }}>
        <div>
          <label htmlFor="mc-scope">Where</label>
          <select id="mc-scope" value={scope}
            onChange={(e) => { setScope(e.target.value); if (e.target.value !== 'other') setOu(''); }}>
            {(scopeList.length ? scopeList : [{ scope: 'facility', short: 'This hospital' }])
              .map((s) => <option key={s.scope} value={s.scope}>{s.short || s.name}</option>)}
            <option value="other">Another facility in the region</option>
          </select>
          {scope !== 'other' && (
            <div className="form-hint">{data.orgUnit?.name}</div>
          )}
        </div>

        {scope === 'other' && (
          <div>
            <label htmlFor="mc-facility">Facility</label>
            {/* A list of six hundred is a search box, not a dropdown. The input
                holds a name and `ou` holds the id only once a name matches one
                exactly, so a half-typed name cannot be charted as somewhere
                else. */}
            <input id="mc-facility" list="mc-facility-list" value={facilityText}
              placeholder={facilities.length
                ? `Search ${facilities.length} facilities`
                : 'Reading the facility list…'}
              onChange={(e) => pickFacility(e.target.value)} />
            <datalist id="mc-facility-list">
              {facilities.map((f) => <option key={f.id} value={f.name} />)}
            </datalist>
            <div className="form-hint">
              {ou ? data.orgUnit?.name : 'Pick a facility to draw its channel.'}
            </div>
          </div>
        )}

        {data.elements?.length > 1 && (
          <div>
            <label htmlFor="mc-element">Case series</label>
            <select id="mc-element" value={element} onChange={(e) => setElement(e.target.value)}>
              {data.elements.map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}
            </select>
          </div>
        )}
        <div>
          <label htmlFor="mc-baseline">Baseline</label>
          <select id="mc-baseline" value={baseline} onChange={(e) => setBaseline(Number(e.target.value))}>
            {years.map((y) => <option key={y} value={y}>{y} previous years</option>)}
          </select>
          <div className="form-hint">
            {data.baselineYears?.[0]}–{data.baselineYears?.[data.baselineYears.length - 1]},
            excluding {data.year} itself
          </div>
        </div>
      </div>

      {/* The guidance is five to ten years. A channel drawn from fewer still
          renders, because a thin channel is more use than none, but it says so
          rather than presenting a threshold it cannot support. */}
      {data.baselineBelowGuidance && (
        <div className="alert warn">
          These thresholds come from {data.baselineYearsUsed} year
          {data.baselineYearsUsed === 1 ? '' : 's'} of history. Uganda&rsquo;s guidance asks for
          five to ten; treat the bands as indicative until more history is available.
        </div>
      )}

      {/* Between choosing "another facility" and naming one there is nothing to
          draw. Leaving the previous chart up would label this hospital's weeks
          with someone else's question. */}
      {scope === 'other' && !ou ? (
        <div className="empty">
          <div className="empty-title">Choose a facility</div>
          <div className="empty-subtitle">
            Start typing a name to draw that facility&rsquo;s channel for {data.year}.
          </div>
        </div>
      ) : (
        <Channel data={data} />
      )}
    </>
  );
}
