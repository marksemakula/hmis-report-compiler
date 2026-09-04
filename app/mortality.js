'use client';
import { useCallback, useEffect, useState } from 'react';
import { isoWeek, weekLabel } from './lib';
import { IconAlert } from './icons';

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


/* Two rings, one centre.
 *
 * Sex inside, age outside, both counting the same certificates, so the rings
 * share a total and a reader can move between them without doing arithmetic.
 *
 * The age ring uses the sequential ramp the district map already uses, because
 * age bands are ORDERED: a categorical palette would let the eye read
 * "20Yrs & above" as a different kind of thing from "10 - 19Yrs" rather than
 * as further along the same scale. Sex is genuinely categorical and takes two
 * hues of its own - violet and orange, 38.7 apart in OKLab and 33.2 under
 * protanopia, and both separable from every step of the blue ramp beside them.
 * Not pink and blue: that convention encodes nothing and misleads about which
 * slice is which.
 */
const SEX_COLOURS = ['#7048e8', '#f76707'];
const AGE_RAMP = ['#e8f1fc', '#bcd7f4', '#7cb0e5', '#3b86d4', '#0a4f96'];
/* "Not recorded" is not a category, it is the absence of one, and it must never
   take a step of the ramp: with a plain index the sixth slice wrapped back to
   the palest blue and read as a second neonatal band. */
const NOT_RECORDED = 'Not recorded';
const NO_VALUE_COLOUR = '#c3c2b7';
const colourFor = (rows, colours) => (row, i) => (
  row.label === NOT_RECORDED ? NO_VALUE_COLOUR : colours[i % colours.length]);
const RING_GAP = 0.012;   // radians of surface between slices, not a border

function arcPath(cx, cy, rOuter, rInner, a0, a1) {
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const at = (r, a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  const [x0, y0] = at(rOuter, a0);
  const [x1, y1] = at(rOuter, a1);
  const [x2, y2] = at(rInner, a1);
  const [x3, y3] = at(rInner, a0);
  return `M${x0.toFixed(2)},${y0.toFixed(2)}`
    + `A${rOuter},${rOuter} 0 ${large} 1 ${x1.toFixed(2)},${y1.toFixed(2)}`
    + `L${x2.toFixed(2)},${y2.toFixed(2)}`
    + `A${rInner},${rInner} 0 ${large} 0 ${x3.toFixed(2)},${y3.toFixed(2)}Z`;
}

function Ring({ rows, colours, rOuter, rInner, total, cx, cy }) {
  if (!total) return null;
  let angle = -Math.PI / 2;
  return rows.map((r, i) => {
    const sweep = (r.deaths / total) * Math.PI * 2;
    const a0 = angle + RING_GAP / 2;
    const a1 = angle + sweep - RING_GAP / 2;
    angle += sweep;
    const colour = colourFor(rows, colours)(r, i);
    // A single category filling the ring has no two ends to draw between, so
    // it is a stroked circle rather than a degenerate arc.
    if (sweep >= Math.PI * 2 - 1e-6) {
      return (
        <circle key={r.label} cx={cx} cy={cy} r={(rOuter + rInner) / 2}
          fill="none" stroke={colour} strokeWidth={rOuter - rInner}>
          <title>{`${r.label}: ${r.deaths}`}</title>
        </circle>
      );
    }
    if (a1 <= a0) return null;
    return (
      <path key={r.label} d={arcPath(cx, cy, rOuter, rInner, a0, a1)} fill={colour}>
        <title>{`${r.label}: ${r.deaths}`}</title>
      </path>
    );
  });
}

function Key({ rows, colours, total }) {
  return (
    <div>
      {rows.map((r, i) => (
        <div key={r.label} className="d-flex items-center gap-2"
          style={{ fontSize: '.6875rem', marginBottom: '.2rem' }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, flex: 'none',
            background: colourFor(rows, colours)(r, i),
            boxShadow: 'inset 0 0 0 1px rgba(4,32,69,.12)' }} />
          <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
            whiteSpace: 'nowrap' }}>{r.label}</span>
          <span className="fw-medium ms-auto" style={{ flex: 'none' }}>{r.deaths}</span>
          <span className="text-secondary" style={{ flex: 'none', width: 34, textAlign: 'right' }}>
            {total ? `${Math.round((r.deaths / total) * 100)}%` : ''}
          </span>
        </div>
      ))}
    </div>
  );
}

function Demographics({ data }) {
  const sex = data.bySex || [];
  const ages = data.byAgeBand || [];
  const sexTotal = sex.reduce((t, r) => t + r.deaths, 0);
  const ageTotal = ages.reduce((t, r) => t + r.deaths, 0);
  if (!sexTotal && !ageTotal) {
    return (
      <div className="text-secondary" style={{ fontSize: '.75rem' }}>
        No certificate in {data.window?.label} records a sex or an age.
      </div>
    );
  }
  const S = 176, c = S / 2;
  return (
    <div className="d-flex gap-3" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
      <svg viewBox={`0 0 ${S} ${S}`} width={S} height={S} style={{ flex: 'none' }} role="img"
        aria-label={`Deaths in ${data.window?.label}: inner ring by sex, outer ring by age band`}>
        <Ring rows={ages} colours={AGE_RAMP} rOuter={84} rInner={62} total={ageTotal} cx={c} cy={c} />
        <Ring rows={sex} colours={SEX_COLOURS} rOuter={56} rInner={34} total={sexTotal} cx={c} cy={c} />
        {/* The total belongs in the hole: it is what both rings add up to, and
            a reader should not have to sum a legend to find it. */}
        <text x={c} y={c - 2} textAnchor="middle" fontSize="22" fontWeight="600" fill="#181818">
          {ageTotal || sexTotal}
        </text>
        <text x={c} y={c + 14} textAnchor="middle" fontSize="10" fill="#181818">deaths</text>
      </svg>

      <div style={{ flex: 1, minWidth: 190 }}>
        <div className="text-secondary" style={{ fontSize: '.625rem', textTransform: 'uppercase',
          letterSpacing: '.04em', marginBottom: '.2rem' }}>Sex, inner ring</div>
        <Key rows={sex} colours={SEX_COLOURS} total={sexTotal} />
        <div className="text-secondary" style={{ fontSize: '.625rem', textTransform: 'uppercase',
          letterSpacing: '.04em', margin: '.45rem 0 .2rem' }}>Age, outer ring</div>
        <Key rows={ages} colours={AGE_RAMP} total={ageTotal} />
      </div>
    </div>
  );
}

export default function Mortality({ scope = 'facility' }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  /* The year, which is how a hospital reads its own mortality: so far this
     year, and last year beside it. A rolling quarter was too thin - 101 causes
     were certified in the whole of 2026 to date. */
  const [chosenYear, setChosenYear] = useState(null);

  /* The week just finished: this week is still being filled in, and a rate
     computed halfway through one reads as a collapse in deaths. */
  const [year, week] = isoWeek(new Date(Date.now() - 7 * 86400000));
  const period = `${year}W${week}`;

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const qs = chosenYear ? `&year=${chosenYear}` : '';
      const r = await fetch(`/api/py/mortality?period=${period}${qs}&scope=${scope}`);
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(b?.detail || `Mortality could not be read (HTTP ${r.status}).`);
      setData(b);
    } catch (e) {
      setData(null);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [period, chosenYear, scope]);

  useEffect(() => { load(); }, [load]);

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

        {/* The rate is the headline; the two counts under it are what the rate
            is made of, because a rate with no denominator cannot be checked. */}
        <div className="d-flex items-baseline gap-2">
          <span className="stat-value">
            {data.ratePerThousand === null || data.ratePerThousand === undefined
              ? 'no rate' : data.ratePerThousand}
          </span>
          <span className="text-secondary" style={{ fontSize: '.75rem' }}>per 1,000 seen</span>
        </div>
        <div className="stat-foot" style={{ marginBottom: '.6rem' }}>
          {data.deaths === null || data.deaths === undefined
            ? 'Deaths not reported for this week'
            : `${nf(data.deaths)} death${data.deaths === 1 ? '' : 's'} of ${nf(data.seen) || 'unknown'} seen`}
        </div>

        <div style={{ borderTop: '1px solid var(--tblr-border-color)', paddingTop: '.5rem',
          marginBottom: '.6rem' }}>
          <div className="d-flex items-center gap-2" style={{ marginBottom: '.5rem' }}>
            <label htmlFor="mort-year" className="text-secondary"
              style={{ fontSize: '.6875rem', marginBottom: 0 }}>Year</label>
            <select id="mort-year" value={data.year}
              onChange={(e) => setChosenYear(Number(e.target.value))}
              style={{ fontSize: '.6875rem', padding: '.15rem .4rem', width: 'auto' }}>
              {(data.years || []).map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <span className="text-secondary ms-auto" style={{ fontSize: '.6875rem' }}>
              {data.eventsRead} certificates in {data.window?.label}
            </span>
          </div>
          <Demographics data={data} />
        </div>

        <div style={{ borderTop: '1px solid var(--tblr-border-color)', paddingTop: '.5rem' }}>
          <div className="d-flex items-center gap-2" style={{ marginBottom: '.35rem' }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: ALL_CAUSE, flex: 'none' }} />
            <span className="fw-medium" style={{ fontSize: '.75rem' }}>All Cause Mortality</span>
            <span className="text-secondary ms-auto" style={{ fontSize: '.6875rem' }}>
              {data.certifiedInWindow} of {data.eventsRead} carry a cause
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
          {' '}{data.denominatorSource}. The MPDSR review forms carry no coded cause at this
          hospital, so those bars are drawn from the certificates themselves: deaths a
          pregnancy contributed to, and stillbirths.
        </div>
      </div>
    </div>
  );
}
