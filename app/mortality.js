'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { isoWeek, weekLabel } from './lib';
import { IconAlert } from './icons';
import useWidth from './usewidth';

/* Deaths, against the people seen, and what they died of.
 *
 * Two groups of bars in one card because they answer one question at two
 * scopes: what kills patients here, and what kills mothers here. They are
 * counted from the same source - the death certificates - so they belong on
 * the same axis and share it.
 *
 * Horizontal bars, because the categories are ICD-11 terms: "Pneumonitis due
 * to inhalation of food or vomit" is not going under a vertical column at any
 * width this card will ever have.
 *
 * Blue and teal measure 23.8 apart in OKLab and 23.1 under protanopia, so the
 * two groups stay separable for a colourblind reader; each group is also
 * headed in words, so colour is never the only thing carrying the distinction.
 */
const ALL_CAUSE = '#066fd1';
const MPDSR = '#0ca678';

/* The inpatient death rate against the hospital's standard.
 *
 * The measure is CI03 over CI02 - deaths over admissions, both HMIS 108, both
 * the monthly inpatient return - so the ratio is one the form itself supports.
 * A death count over OPD attendances, which is what this card used to show,
 * divides a ward number by a door number.
 *
 * A line against a baseline, not two lines. Admissions run in the thousands
 * and deaths in the tens, so plotting both on one axis flattens deaths into
 * the floor, and giving them a second axis invents a correlation out of where
 * the two scales happen to be pinned. The rate IS deaths against admissions,
 * on one axis, and both raw counts read in the tooltip and the footer.
 *
 * Blue for the rate, red for a month over the standard: 23.4 apart in the
 * worst colour-vision case, and a month over is also labelled with its figure,
 * so the breach never rests on colour. The standard itself is a recessive gray
 * rule, dashed and named, so it reads as a limit rather than a third series -
 * the ordinary gridlines are solid hairlines for the same reason. */
const RATE = '#066fd1';
const OVER = '#d63939';
const STANDARD_RULE = '#6b7280';

const nf = (n) => (n === null || n === undefined ? null : Number(n).toLocaleString('en-GB'));

function Bars({ rows, colour, max, empty }) {
  if (!rows || rows.length === 0) {
    return <div className="text-secondary" style={{ fontSize: '.75rem' }}>{empty}</div>;
  }
  return (
    <div>
      {rows.map((r) => (
        <div key={r.cause} className="d-flex items-center gap-2"
          style={{ marginBottom: '.3rem', fontSize: '.75rem' }}>
          <span style={{
            width: '46%', flex: 'none', whiteSpace: 'nowrap', overflow: 'hidden',
            textOverflow: 'ellipsis',
          }} title={r.cause}>{r.cause}</span>
          <span style={{ flex: 1, minWidth: 0 }}>
            <span style={{
              display: 'block', height: 12, borderRadius: 2, background: colour,
              width: `${Math.max(3, (r.deaths / Math.max(max, 1)) * 100)}%`,
            }} />
          </span>
          {/* The value at the tip. Ten bars is few enough that every one can
              carry its number, which is what stops the reader estimating from
              a length they cannot measure. */}
          <span className="fw-medium" style={{ width: 24, textAlign: 'right', flex: 'none' }}>
            {r.deaths}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Anchor a tooltip to a column, flipping it inboard near either edge. */
function tipShift(percent) {
  return percent > 72 ? 'translateX(-100%)' : percent < 18 ? 'translateX(0)' : 'translateX(-50%)';
}

const TIP = {
  position: 'absolute', top: 0, pointerEvents: 'none',
  background: '#fff', border: '1px solid rgba(4,32,69,.1)', borderRadius: 6,
  boxShadow: '0 16px 24px 2px rgba(0,0,0,.07)', padding: '.4rem .5rem',
  fontSize: '.6875rem', whiteSpace: 'nowrap', zIndex: 2,
};

/* Deaths as a share of admissions, month by month, against the standard.
 *
 * One measure on one axis. The y scale starts at zero because a rate is a
 * magnitude and a truncated baseline exaggerates every wobble in it; it ends
 * above whichever is larger, the standard or the worst month, so the standard
 * is always on the chart even in a good year and a breach is never off the
 * top of it.
 *
 * Only two points are labelled: the last month, and the worst month when that
 * is a different one and it is over the standard. A number on every point is
 * chaos and goes unread; the crosshair carries the rest. */
function RateTrend({ months, standard }) {
  const box = useRef(null);
  const W = useWidth(box, 360);
  const [hover, setHover] = useState(null);

  const points = (months || []).filter((m) => m.rate !== null && m.rate !== undefined);
  if (points.length === 0) {
    return (
      <div className="text-secondary" style={{ fontSize: '.75rem' }}>
        No month has both an admission and a death figure, so no rate can be drawn.
      </div>
    );
  }

  const H = 132;
  const padL = 30, padR = 12, padT = 12, padB = 20;
  const plotW = Math.max(40, W - padL - padR);
  const plotH = H - padT - padB;

  const worst = points.reduce((a, b) => (b.rate > a.rate ? b : a), points[0]);
  const top = Math.max(standard, worst.rate) * 1.25 || 1;
  const xOf = (i) => (points.length === 1
    ? padL + plotW / 2
    : padL + (plotW / (points.length - 1)) * i);
  const yOf = (v) => padT + plotH - (Math.min(v, top) / top) * plotH;

  // Three gridlines, solid hairlines. The standard gets its own rule, dashed
  // and labelled, so it does not read as a fourth gridline.
  const ticks = [0, top / 2, top].map((v) => Math.round(v * 10) / 10);
  const last = points[points.length - 1];
  const labelled = new Set([last.period]);
  if (worst.overStandard && worst.period !== last.period) labelled.add(worst.period);
  const active = hover === null ? null : points[hover];

  return (
    <div ref={box} style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}
        style={{ width: '100%', height: `${H}px`, display: 'block' }} role="img"
        aria-label={`Deaths as a share of admissions by month, against a standard of ${standard}% or less`}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={padL} x2={W - padR} y1={yOf(v)} y2={yOf(v)}
              stroke="#e5e7eb" strokeWidth="1" />
            <text x={padL - 6} y={yOf(v) + 3.5} textAnchor="end" fontSize="9" fill="#6b7280">
              {v}%
            </text>
          </g>
        ))}

        {/* The standard. Dashed and named, because it is a limit rather than
            a reading, and a solid rule at this weight reads as a series. */}
        <line x1={padL} x2={W - padR} y1={yOf(standard)} y2={yOf(standard)}
          stroke={STANDARD_RULE} strokeWidth="1.5" strokeDasharray="4 3" />
        {/* Named at the left, where no endpoint label lands. Every label on
            this plot carries a surface halo as well: the standard rule and the
            line it judges necessarily sit close together in a good year, and a
            figure printed straight over a dash is unreadable. */}
        <text x={padL + 2} y={yOf(standard) - 4} textAnchor="start" fontSize="9"
          fill={STANDARD_RULE} stroke="#fff" strokeWidth="3" paintOrder="stroke">
          Standard {standard}%
        </text>

        <path d={points.map((p, i) => `${i ? 'L' : 'M'}${xOf(i)},${yOf(p.rate)}`).join('')}
          fill="none" stroke={RATE} strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" />

        {points.map((p, i) => (
          <g key={p.period}>
            {/* A 2px surface ring keeps a marker legible where it sits on the
                line and widens the target at the same time. */}
            <circle cx={xOf(i)} cy={yOf(p.rate)} r={hover === i ? 5 : 4}
              fill={p.overStandard ? OVER : RATE} stroke="#fff" strokeWidth="2" />
            {labelled.has(p.period) && (
              <text x={xOf(i)} y={yOf(p.rate) - 9}
                textAnchor={i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'}
                fontSize="10" fontWeight="700" fill={p.overStandard ? OVER : '#111827'}
                stroke="#fff" strokeWidth="3" paintOrder="stroke">
                {p.rate}%
              </text>
            )}
            {(points.length <= 6 || i % 2 === 0 || i === points.length - 1) && (
              <text x={xOf(i)} y={H - 6} textAnchor="middle" fontSize="9" fill="#6b7280">
                {p.short}
              </text>
            )}
            <rect x={xOf(i) - plotW / Math.max(1, points.length - 1) / 2} y={padT}
              width={plotW / Math.max(1, points.length - 1)} height={plotH} fill="transparent"
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
          </g>
        ))}
      </svg>

      {active && (() => {
        const p = (xOf(hover) / W) * 100;
        return (
          <div style={{ ...TIP, left: `${p}%`, transform: tipShift(p) }}>
            <div className="fw-bold">{active.label}</div>
            <div style={{ color: active.overStandard ? OVER : 'inherit' }}>
              {active.rate}% of admissions{active.overStandard ? ' · over standard' : ''}
            </div>
            <div className="text-secondary">
              {nf(active.deaths)} deaths (CI03) of {nf(active.admissions)} admissions (CI02)
            </div>
          </div>
        );
      })()}
    </div>
  );
}

export default function Mortality({ scope = 'facility' }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  /* Year to date by default. A rolling quarter is too thin at this hospital:
     101 causes were certified in the whole of 2026 to date, so thirteen weeks
     of them is a top five of threes and twos. */
  const [windowKey, setWindowKey] = useState('ytd');
  // The rate and the causes come from two different returns - 108 monthly and
  // the certificates - so they are two requests. Folding them into one would
  // make the causes wait on a series they have nothing to do with.
  const [ip, setIp] = useState(null);
  const [ipError, setIpError] = useState('');

  /* The week just finished: this week is still being filled in, and a rate
     computed halfway through one reads as a collapse in deaths. */
  const [year, week] = isoWeek(new Date(Date.now() - 7 * 86400000));
  const period = `${year}W${week}`;

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`/api/py/mortality?period=${period}&window=${windowKey}&scope=${scope}`);
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(b?.detail || `Mortality could not be read (HTTP ${r.status}).`);
      setData(b);
    } catch (e) {
      setData(null);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [period, windowKey, scope]);

  const loadRate = useCallback(async () => {
    setIpError('');
    try {
      const r = await fetch(`/api/py/mortality/inpatient?scope=${scope}`);
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(b?.detail || `The death rate could not be read (HTTP ${r.status}).`);
      setIp(b);
    } catch (e) {
      setIp(null);
      setIpError(e.message);
    }
  }, [scope]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadRate(); }, [loadRate]);

  if (loading && !data) {
    return (
      <div className="card">
        <div className="card-body">
          <div className="loading-bar" style={{ marginBottom: '.75rem' }} />
          <div className="text-secondary" style={{ fontSize: '.75rem' }}>
            Reading death certificates from DHIS2…
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <div className="card-body">
          <div className="d-flex items-center gap-2" style={{ marginBottom: '.5rem' }}>
            <IconAlert size={18} />
            <span className="fw-medium">Mortality unavailable</span>
          </div>
          <div className="text-secondary" style={{ fontSize: '.75rem', marginBottom: '.5rem' }}>{error}</div>
          <button type="button" className="btn secondary sm" onClick={load}>Try again</button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const max = Math.max(
    1,
    ...(data.allCause || []).map((r) => r.deaths),
    ...(data.mpdsr || []).map((r) => r.deaths),
  );

  return (
    <div className="card">
      <div className="card-body">
        <div className="d-flex items-center gap-2" style={{ marginBottom: '.25rem' }}>
          <span className="page-pretitle">Mortality</span>
          <span className="text-secondary ms-auto" style={{ fontSize: '.6875rem' }}>
            {weekLabel(Number(String(data.period).slice(0, 4)),
              Number(String(data.period).slice(5)))}
          </span>
        </div>

        {/* The rate is the headline and the standard is stated beside it,
            because a rate with nothing to measure it against is a number
            nobody can act on. The two counts under it are what the rate is
            made of: a rate with no denominator cannot be checked. */}
        {ipError ? (
          <div className="stat-foot" style={{ marginBottom: '.6rem' }}>{ipError}</div>
        ) : !ip ? (
          <div className="loading-bar" style={{ margin: '.5rem 0 .75rem' }} />
        ) : (
          <>
            <div className="d-flex items-baseline gap-2" style={{ flexWrap: 'wrap' }}>
              <span className={`stat-value${ip.withinStandard === false ? ' is-danger' : ''}`}>
                {ip.rate === null || ip.rate === undefined ? '—' : `${ip.rate}%`}
              </span>
              <span className="text-secondary" style={{ fontSize: '.75rem' }}>
                of admissions
              </span>
              {ip.withinStandard !== null && ip.withinStandard !== undefined && (
                /* The verdict in a word as well as a colour, because a badge
                   whose only content is a hue is not readable by everyone. */
                <span className={`badge ${ip.withinStandard ? 'ok' : 'bad'} ms-auto`}>
                  {ip.withinStandard ? 'Within standard' : 'Over standard'}
                </span>
              )}
            </div>
            <div className="stat-foot">
              Standard: {ip.standard}% or less of total admissions
            </div>
            <div className="stat-foot" style={{ marginBottom: '.5rem' }}>
              {ip.resolved === false
                ? 'HMIS 108 CI02 and CI03 are not in the cached metadata, so no rate can be drawn.'
                : ip.deaths === null
                  ? `No 108 admission or death figure for ${ip.periodLabel}`
                  : `${nf(ip.deaths)} death${ip.deaths === 1 ? '' : 's'} (CI03) of `
                    + `${nf(ip.admissions)} admission${ip.admissions === 1 ? '' : 's'} (CI02)`
                    + ` · ${ip.periodLabel}`}
              {ip.monthsOverStandard > 0 && (
                <> · <span className="fw-medium" style={{ color: OVER }}>
                  {ip.monthsOverStandard} month{ip.monthsOverStandard === 1 ? '' : 's'} over
                </span></>
              )}
            </div>
            {ip.resolved !== false && (
              <div style={{ marginBottom: '.6rem' }}>
                <RateTrend months={ip.months} standard={ip.standard} />
              </div>
            )}
          </>
        )}

        <div style={{ borderTop: '1px solid var(--tblr-border-color)', paddingTop: '.5rem' }}>
          <div className="d-flex items-center gap-2" style={{ marginBottom: '.5rem' }}>
            <label htmlFor="mort-window" className="text-secondary"
              style={{ fontSize: '.6875rem', marginBottom: 0 }}>Causes counted</label>
            <select id="mort-window" value={windowKey} onChange={(e) => setWindowKey(e.target.value)}
              style={{ fontSize: '.6875rem', padding: '.15rem .4rem', width: 'auto' }}>
              {(data.windows || []).map((w) => (
                <option key={w.key} value={w.key}>{w.label}</option>
              ))}
            </select>
            <span className="text-secondary ms-auto" style={{ fontSize: '.6875rem' }}>
              {data.certifiedInWindow} of {data.eventsRead} certificates carry a cause
            </span>
          </div>
          <div className="d-flex items-center gap-2" style={{ marginBottom: '.35rem' }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: ALL_CAUSE, flex: 'none' }} />
            <span className="fw-medium" style={{ fontSize: '.75rem' }}>All Cause Mortality</span>
            <span className="text-secondary ms-auto" style={{ fontSize: '.6875rem' }}>
              {data.certifiedInWindow} deaths
            </span>
          </div>
          <Bars rows={data.allCause} colour={ALL_CAUSE} max={max}
            empty="No certificate in this window carries an underlying cause." />
        </div>

        <div style={{ marginTop: '.6rem', borderTop: '1px solid var(--tblr-border-color)', paddingTop: '.5rem' }}>
          <div className="d-flex items-center gap-2" style={{ marginBottom: '.35rem' }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: MPDSR, flex: 'none' }} />
            {/* The full name, and under it the split: "MPDSR" over a single set
                of bars does not say which half they came from, and here it is
                mostly the perinatal half. */}
            <span className="fw-medium" style={{ fontSize: '.75rem', minWidth: 0 }}>
              Maternal and Perinatal Death Surveillance and Response
            </span>
            <span className="text-secondary ms-auto" style={{ fontSize: '.6875rem', flex: 'none' }}>
              {data.maternalInWindow} maternal, {data.perinatalInWindow} perinatal
            </span>
          </div>
          <Bars rows={data.mpdsr} colour={MPDSR} max={max}
            empty="No certificate in this window records a maternal or perinatal death." />
        </div>

        {/* Where the numbers come from, in one line, because a reader who does
            not know that these are certificates rather than the inpatient
            register will read the bars as the whole of the hospital's deaths. */}
        <div className="text-secondary" style={{ fontSize: '.6875rem', marginTop: '.6rem' }}>
          Causes from the medical certificates of cause of death (HMIS 100); the rate from
          {' '}HMIS 108, CI03 deaths over CI02 admissions. The MPDSR review forms carry no coded cause at this
          hospital, so those bars are drawn from the certificates themselves: deaths a
          pregnancy contributed to, and stillbirths.
        </div>
      </div>
    </div>
  );
}
