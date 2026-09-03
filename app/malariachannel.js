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
/* Ink, two thresholds, one band. That is the whole palette.
 *
 * What it replaced: four filled zones stacked to the top of the plot. Because
 * this year's weekly counts run four to six times the thresholds, the epidemic
 * fill covered about seventy per cent of the canvas and the channel itself was
 * squeezed into a strip at the bottom. A reader saw a red page, which says
 * nothing, and could not read the limits at all.
 *
 * Now only the expected range is filled, in a neutral grey that competes with
 * nothing; above it, two lines and white space. The line that matters is drawn
 * in ink.
 *
 * On the amber: measured against this surface it is 2.08:1, below the 3:1 a
 * mark should clear, and darkening it collides with the red - a darker orange
 * measures 13.7 from #d63939 in OKLab, under the 15 at which full-colour
 * readers can still tell two marks apart. It keeps its hue and earns the
 * contrast back the way the guidance allows: a visible label on the line
 * itself, plus every figure in the tooltip.
 */
const INK = '#0b0b0b';
const MUTED = '#898781';
const BAND_FILL = 'rgba(82,81,78,.13)';
const ALERT_COLOUR = '#f59f00';
const EPIDEMIC_COLOUR = '#d63939';

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

  const H = 320;
  // padR holds the labels that name each line at its right-hand end.
  const padL = 52, padR = 104, padT = 20, padB = 40;
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

  /* The last week each series has a value for, which is where its label goes. */
  const lastValue = (key) => {
    for (let i = weeks.length - 1; i >= 0; i -= 1) {
      const v = weeks[i][key];
      if (v !== null && v !== undefined) return v;
    }
    return null;
  };

  /* Push the labels apart until none overlaps, then lift the stack back inside
     the plot if it has run past the bottom. Four labels, so this is exact. */
  const labels = useMemo(() => {
    const wanted = [
      { text: 'Epidemic', colour: EPIDEMIC_COLOUR, dash: null, value: lastValue('epidemic') },
      { text: 'Alert', colour: ALERT_COLOUR, dash: null, value: lastValue('alert') },
      { text: 'Median', colour: MUTED, dash: '5 3', value: lastValue('median') },
      { text: 'Lower limit', colour: MUTED, dash: '2 3', value: lastValue('low') },
    ].filter((l) => l.value !== null).map((l) => ({ ...l, y: yOf(l.value) }));
    const out = wanted.sort((a, b) => a.y - b.y);
    for (let i = 1; i < out.length; i += 1) {
      if (out[i].y - out[i - 1].y < 15) out[i].y = out[i - 1].y + 15;
    }
    const overflow = out.length ? out[out.length - 1].y - (padT + plotH) : 0;
    if (overflow > 0) out.forEach((o) => { o.y -= overflow; });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weeks, top, plotH]);

  let latest = -1;
  weeks.forEach((w, i) => { if (w.current !== null && w.current !== undefined) latest = i; });
  const reportedWeeks = weeks.filter((w) => w.current !== null && w.current !== undefined).length;

  const active = hover === null ? null : weeks[hover];
  const st = STATUS[data.status] || STATUS.unknown;

  return (
    <div ref={box} style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}
        style={{ width: '100%', height: `${H}px`, display: 'block' }} role="img"
        aria-label={`Weekly malaria cases for ${data.orgUnit?.name} in ${data.year}, against percentile bands from ${data.baselineYears?.join(', ')}`}>
        <text x={padL - 44} y="12" fontSize="11" fill={MUTED}>Cases</text>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={padL} x2={padL + plotW} y1={yOf(v)} y2={yOf(v)} stroke="#e1e0d9" strokeWidth="1" />
            <text x={padL - 8} y={yOf(v) + 4} textAnchor="end" fontSize="11" fill={MUTED}>
              {v >= 1000 ? `${Math.round(v / 1000)}k` : Math.round(v)}
            </text>
          </g>
        ))}

        {/* One fill: the expected range. Everything above it is white space
            with two lines across it, which is what makes the lines readable. */}
        <path d={areaPath((w) => w.low, (w) => w.alert)} fill={BAND_FILL} />

        <path d={linePath((w) => w.low)} fill="none" stroke={MUTED}
          strokeWidth="1.25" strokeDasharray="2 3" />
        <path d={linePath((w) => w.median)} fill="none" stroke={MUTED}
          strokeWidth="1.25" strokeDasharray="5 3" />
        <path d={linePath((w) => w.alert)} fill="none" stroke={ALERT_COLOUR} strokeWidth="2" />
        <path d={linePath((w) => w.epidemic)} fill="none" stroke={EPIDEMIC_COLOUR} strokeWidth="2" />
        <path d={linePath((w) => w.current)} fill="none" stroke={INK}
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

        {/* Each line named where it ends, nudged apart so two never overlap.
            Four labels here are four fewer legend entries to match by colour,
            and they are what makes the amber legible at its contrast. */}
        {labels.map((l) => (
          <g key={l.text}>
            <line x1={padL + plotW + 4} x2={padL + plotW + 16} y1={l.y} y2={l.y}
              stroke={l.colour} strokeWidth="2"
              strokeDasharray={l.dash || undefined} />
            <text x={padL + plotW + 20} y={l.y + 4} fontSize="11" fill="#52514e">{l.text}</text>
          </g>
        ))}

        {weeks.map((w, i) => (w.current === null || w.current === undefined ? null : (
          <circle key={w.week} cx={xOf(i)} cy={yOf(w.current)} r={hover === i ? 4.5 : 3}
            fill={INK} stroke="#fcfcfb" strokeWidth="2" />
        )))}

        {/* The one point worth labelling: where this hospital stands now. A
            value beside every dot would be chaos and goes unread. */}
        {latest >= 0 && (
          <g>
            <circle cx={xOf(latest)} cy={yOf(weeks[latest].current)} r="5"
              fill={data.status === 'epidemic' ? EPIDEMIC_COLOUR : INK}
              stroke="#fcfcfb" strokeWidth="2" />
            <text x={xOf(latest) + (xOf(latest) > padL + plotW - 130 ? -10 : 10)}
              y={yOf(weeks[latest].current) - 10} fontSize="11" fontWeight="600" fill={INK}
              textAnchor={xOf(latest) > padL + plotW - 130 ? 'end' : 'start'}>
              Week {weeks[latest].week}: {nf(weeks[latest].current)}
            </text>
          </g>
        )}

        {weeks.map((w, i) => (
          <g key={`x${w.week}`}>
            {(w.week === 1 || w.week % 4 === 0) && (
              <text x={xOf(i)} y={H - 22} textAnchor="middle" fontSize="11" fill={MUTED}>{w.week}</text>
            )}
            <rect x={xOf(i) - plotW / Math.max(weeks.length - 1, 1) / 2} y={padT}
              width={plotW / Math.max(weeks.length - 1, 1)} height={plotH} fill="transparent"
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
          </g>
        ))}
        <text x={padL + plotW / 2} y={H - 5} textAnchor="middle" fontSize="11" fill={MUTED}>
          ISO week
        </text>
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
        {/* Only the two marks the plot cannot name at their own right-hand end.
            Nine legend entries was itself the problem: a row of pale swatches
            that had to be matched back to four pale fills. */}
        <span className="d-flex items-center gap-2">
          <span style={{ width: 16, height: 2, background: INK, flex: 'none' }} />
          <span className="text-secondary">
            {data.year} cases{reportedWeeks ? `, ${reportedWeeks} weeks reported` : ''}
          </span>
        </span>
        <span className="d-flex items-center gap-2">
          <span style={{ width: 16, height: 12, background: BAND_FILL, flex: 'none',
            boxShadow: 'inset 0 0 0 1px rgba(4,32,69,.12)' }} />
          <span className="text-secondary">
            Expected range: the {data.lowPercentile ?? 25}th to {data.alertPercentile ?? 75}th
            percentile of the same week in {data.baselineYears?.[0]} to
            {' '}{data.baselineYears?.[data.baselineYears.length - 1]}
          </span>
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
          Most weeks here are built on {data.baselineYearsUsed} previous year
          {data.baselineYearsUsed === 1 ? '' : 's'}, not
          {' '}{data.baselineYears?.length}: the earlier years are incomplete in this
          register{data.baselineYearsBest > data.baselineYearsUsed
            ? `, and only the best-covered week reaches ${data.baselineYearsBest}`
            : ''}. Uganda&rsquo;s guidance asks for five to ten, so treat the limits as
          indicative until more history is available.
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
