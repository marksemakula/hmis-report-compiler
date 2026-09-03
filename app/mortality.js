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

export default function Mortality({ scope = 'facility' }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  /* The week just finished: this week is still being filled in, and a rate
     computed halfway through one reads as a collapse in deaths. */
  const [year, week] = isoWeek(new Date(Date.now() - 7 * 86400000));
  const period = `${year}W${week}`;

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`/api/py/mortality?period=${period}&weeks=12&scope=${scope}`);
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(b?.detail || `Mortality could not be read (HTTP ${r.status}).`);
      setData(b);
    } catch (e) {
      setData(null);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [period, scope]);

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

        <div style={{ borderTop: '1px solid var(--tblr-border-color)', paddingTop: '.5rem' }}>
          <div className="d-flex items-center gap-2" style={{ marginBottom: '.35rem' }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: ALL_CAUSE, flex: 'none' }} />
            <span className="fw-medium" style={{ fontSize: '.75rem' }}>All Cause Mortality</span>
            <span className="text-secondary ms-auto" style={{ fontSize: '.6875rem' }}>
              {data.certifiedInWindow} certified in {data.window?.weeks} weeks
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
