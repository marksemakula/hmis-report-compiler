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

const BANDS = [
  { key: 'normal', label: 'Expected', fill: 'rgba(47,179,68,.16)' },
  { key: 'alert', label: 'Alert (>75th percentile)', fill: 'rgba(245,159,0,.20)' },
  { key: 'epidemic', label: 'Epidemic (>85th percentile)', fill: 'rgba(214,57,57,.16)' },
];

const STATUS = {
  normal: { badge: 'ok', word: 'Within the expected channel' },
  alert: { badge: 'warn', word: 'Above the alert threshold' },
  epidemic: { badge: 'bad', word: 'Above the epidemic threshold' },
  unknown: { badge: 'muted', word: 'Not enough data to classify' },
};

const nf = (n) => (n === null || n === undefined ? '—' : Number(n).toLocaleString('en-GB'));

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

        <path d={areaPath(() => 0, (w) => w.alert)} fill={BANDS[0].fill} />
        <path d={areaPath((w) => w.alert, (w) => w.epidemic)} fill={BANDS[1].fill} />
        <path d={areaPath((w) => w.epidemic, () => top)} fill={BANDS[2].fill} />

        <path d={linePath((w) => w.median)} fill="none" stroke="#6b7280"
          strokeWidth="1.5" strokeDasharray="4 3" />
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
            <div className="d-flex items-center gap-2">
              <span className="text-secondary">This year</span>
              <span className="ms-auto fw-medium" style={{ paddingLeft: '1rem' }}>{nf(active.current)}</span>
            </div>
            <div className="d-flex items-center gap-2">
              <span className="text-secondary">Epidemic threshold</span>
              <span className="ms-auto fw-medium" style={{ paddingLeft: '1rem' }}>
                {active.epidemic === null ? '—' : Math.round(active.epidemic).toLocaleString('en-GB')}
              </span>
            </div>
            <div className="d-flex items-center gap-2">
              <span className="text-secondary">Alert threshold</span>
              <span className="ms-auto fw-medium" style={{ paddingLeft: '1rem' }}>
                {active.alert === null ? '—' : Math.round(active.alert).toLocaleString('en-GB')}
              </span>
            </div>
            <div className="d-flex items-center gap-2">
              <span className="text-secondary">Median of {active.n} year{active.n === 1 ? '' : 's'}</span>
              <span className="ms-auto fw-medium" style={{ paddingLeft: '1rem' }}>
                {active.median === null ? '—' : Math.round(active.median).toLocaleString('en-GB')}
              </span>
            </div>
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

export default function MalariaChannel({ scope = 'facility' }) {
  const [data, setData] = useState(null);
  const [element, setElement] = useState('');
  const [baseline, setBaseline] = useState(5);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const qs = new URLSearchParams({ scope, baseline: String(baseline) });
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
  }, [scope, element, baseline]);

  useEffect(() => { load(); }, [load]);

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

      <Channel data={data} />
    </>
  );
}
