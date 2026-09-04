'use client';
import { useCallback, useEffect, useState } from 'react';
import { IconAlert } from './icons';

/* The four death lines of HMIS 033B, cumulative from week 1.
 *
 *   CD20  MD  Maternal death
 *   CD21  MB  Macerated still birth
 *   CD22  FB  Fresh still birth
 *   CD23  EN  Early neonatal death, 0 to 7 days
 *
 * Counts, not a chart. Four numbers that are usually small and sometimes zero
 * have no shape worth drawing: a bar chart of 0, 2, 1, 3 spends a card on
 * three pixels of ink and makes the difference between two and three look like
 * the point. The numbers themselves are the point, so they are set large
 * enough to read across a room and left alone.
 *
 * The form's own code and abbreviation travel with each line. This tile is
 * read next to the paper register, and CD21/MB is how the register names the
 * row - a reader checking one against the other should not have to translate.
 *
 * Two states are kept apart on purpose, because for a death count they are
 * opposite claims:
 *
 *   0     nobody died in the weeks that were filed
 *   none  this instance's 033B has no such line, so nobody knows
 *
 * A tile that printed 0 for both would be worse than one that printed neither.
 */

const nf = (n) => Number(n || 0).toLocaleString('en-GB');

export default function PerinatalDeaths({ scope = 'facility' }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`/api/py/surveillance/deaths?scope=${encodeURIComponent(scope)}`);
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(b?.detail || `Death figures unavailable (HTTP ${r.status}).`);
      setData(b);
    } catch (e) {
      setData(null);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => { load(); }, [load]);

  const shell = (body) => (
    <div className="card">
      <div className="card-body">
        <div className="page-pretitle">Maternal and perinatal deaths · 033B</div>
        {body}
      </div>
    </div>
  );

  if (loading && !data) {
    return shell(
      <>
        <div className="loading-bar" style={{ margin: '.75rem 0 .5rem' }} />
        <div className="text-secondary" style={{ fontSize: '.75rem' }}>Reading DHIS2…</div>
      </>
    );
  }

  if (error) {
    return shell(
      <div className="empty" style={{ padding: '.75rem 0 .25rem' }}>
        <div className="empty-icon"><IconAlert size={24} /></div>
        <div className="empty-subtitle" style={{ marginBottom: '.625rem', fontSize: '.75rem' }}>
          {error}
        </div>
        <button type="button" className="btn secondary sm" onClick={load}>Try again</button>
      </div>
    );
  }

  if (!data) return shell(null);

  const lines = data.lines || [];
  const missing = lines.filter((l) => l.value === null);
  const thin = data.reported && data.weeksReported < data.weeksElapsed;

  return shell(
    <>
      <div style={{ marginTop: '.5rem' }}>
        {lines.map((l) => (
          <div key={l.code} className="d-flex items-center gap-2"
            style={{ padding: '.3125rem 0', borderTop: '1px solid rgba(4,32,69,.08)' }}>
            <span className="fw-bold" style={{ flex: 'none', width: '2.25rem',
              fontSize: '.6875rem', letterSpacing: '.02em', color: 'var(--tblr-primary)' }}>
              {l.short}
            </span>
            <span style={{ minWidth: 0, flex: 1, fontSize: '.8125rem',
              color: 'var(--tblr-body-color)' }}>
              {l.label}
              <span className="text-secondary" style={{ fontSize: '.6875rem' }}> · {l.code}</span>
            </span>
            {/* A resolved line prints its count, including zero. An unresolved
                one prints nothing at all, and says why below. */}
            {l.value === null ? (
              <span className="text-secondary" style={{ flex: 'none', paddingLeft: '.75rem',
                fontSize: '.75rem', whiteSpace: 'nowrap' }}>not on this form</span>
            ) : (
              <span className="fw-bold" style={{ flex: 'none', paddingLeft: '.75rem',
                fontSize: '1.125rem', whiteSpace: 'nowrap',
                color: l.value > 0 ? 'var(--tblr-danger)' : 'var(--tblr-body-color)' }}>
                {nf(l.value)}
              </span>
            )}
          </div>
        ))}
      </div>

      {missing.length > 0 && (
        <div className="stat-foot">
          {missing.length === lines.length
            ? 'No 033B death line could be resolved from the cached metadata.'
            : `${missing.map((l) => l.code).join(', ')} could not be resolved from the
               cached metadata, so ${missing.length === 1 ? 'it is' : 'they are'} blank
               rather than zero.`}
        </div>
      )}

      <div className="stat-foot">
        {data.periodLabel} · {data.orgUnit?.name}
        {thin && (
          <> · <span className="fw-medium" style={{ color: 'var(--tblr-danger)' }}>
            {data.weeksReported} of {data.weeksElapsed} weeks reported
          </span></>
        )}
        {data.reported === false && lines.some((l) => l.value !== null) && (
          <> · <span className="fw-medium" style={{ color: 'var(--tblr-danger)' }}>
            no week reported
          </span></>
        )}
      </div>
    </>
  );
}
