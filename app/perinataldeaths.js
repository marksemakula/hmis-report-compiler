'use client';
import { useCallback, useEffect, useState } from 'react';
import { IconAlert } from './icons';
import { SCOPE_LEVELS, yearLabel } from './lib';

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
 * Level and Period are the same two filters, in the same order, behind the
 * same Load button as the screening card beside it. A dashboard where the card
 * on the left defers to a button and the card on the right redraws on every
 * keystroke teaches two habits for one gesture.
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

const asQuery = (q) => {
  const p = new URLSearchParams({ scope: q.scope });
  // Empty means "whatever the server calls this year", which is not the same
  // as a year worked out from the browser's clock.
  if (q.year) p.set('year', q.year);
  return p.toString();
};

export default function PerinatalDeaths({ scope = 'facility' }) {
  /* `draft` is what the controls show and `applied` is what the figures were
     read with; only Load moves one to the other. The `scope` prop is the
     starting level, not a standing one: from the first render the card owns
     its own filters. */
  const [draft, setDraft] = useState({ scope, year: '' });
  const [applied, setApplied] = useState({ scope, year: '' });
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const query = asQuery(applied);
  const dirty = query !== asQuery(draft);
  const years = data?.years || [];
  const currentYear = data?.currentYear ?? years[0];

  const load = useCallback(async (qs) => {
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`/api/py/surveillance/deaths?${qs}`);
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(b?.detail || `Death figures unavailable (HTTP ${r.status}).`);
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

  /* The card is narrower than the screening card, so the controls are sized to
     their content and allowed to wrap rather than being squeezed to fit one
     line. A select too narrow to show "MoH - National" is worse than a second
     row of controls. */
  const picker = (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: '.5rem',
      flexWrap: 'wrap', margin: '.375rem 0 .25rem' }}>
      <div style={{ minWidth: 0 }}>
        <label className="form-label sm" htmlFor="deaths-level">Level</label>
        <select id="deaths-level" className="sm" style={{ width: 'auto', minWidth: '9rem' }}
          value={draft.scope} onChange={(e) => set({ scope: e.target.value })}>
          {SCOPE_LEVELS.map((l) => (
            <option key={l.scope} value={l.scope}>{l.label}</option>
          ))}
        </select>
      </div>
      <div style={{ minWidth: 0 }}>
        <label className="form-label sm" htmlFor="deaths-period">Period</label>
        {years.length ? (
          <select id="deaths-period" className="sm" style={{ width: 'auto', minWidth: '10rem' }}
            value={draft.year || String(data?.year || '')}
            onChange={(e) => set({ year: e.target.value })}>
            {years.map((y) => (
              <option key={y} value={y}>{yearLabel(y, currentYear)}</option>
            ))}
          </select>
        ) : (
          // Before the first answer the server has not said which years exist.
          <select id="deaths-period" className="sm" disabled
            style={{ width: 'auto', minWidth: '10rem' }}>
            <option>Reading…</option>
          </select>
        )}
      </div>
      <button type="button" id="deaths-load" className={`btn sm${dirty ? '' : ' secondary'}`}
        disabled={loading || !dirty} onClick={() => setApplied(draft)}>
        {loading ? 'Loading…' : 'Load'}
      </button>
    </div>
  );

  const shell = (body) => (
    <div className="card">
      <div className="card-body">
        <div className="page-pretitle">Maternal and perinatal deaths · 033B</div>
        {picker}
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
        <button type="button" className="btn secondary sm"
          onClick={() => load(query)}>Try again</button>
      </div>
    );
  }

  if (!data) return shell(null);

  const lines = data.lines || [];
  const missing = lines.filter((l) => l.value === null);
  const thin = data.reported && data.weeksReported < data.weeksElapsed;

  return shell(
    <>
      <div>
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
