'use client';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiGet } from '../lib';

const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];

/* ISO-8601 week number, matching the DHIS2 Weekly period type. */
function isoWeek(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return [t.getUTCFullYear(), Math.ceil(((t - yearStart) / 86400000 + 1) / 7)];
}
const weeksInYear = (y) => isoWeek(new Date(y, 11, 28))[1];

/* Split a DHIS2 period identifier into its year and ordinal parts. */
function splitPeriod(periodType, period) {
  const p = String(period || '');
  if (periodType === 'Weekly')    { const m = p.match(/^(\d{4})W(\d{1,2})$/i); return m ? [+m[1], +m[2]] : [new Date().getFullYear(), 1]; }
  if (periodType === 'Quarterly') { const m = p.match(/^(\d{4})Q([1-4])$/i);   return m ? [+m[1], +m[2]] : [new Date().getFullYear(), 1]; }
  const m = p.match(/^(\d{4})(\d{2})$/); return m ? [+m[1], +m[2]] : [new Date().getFullYear(), 1];
}
function joinPeriod(periodType, year, n) {
  if (periodType === 'Weekly')    return `${year}W${n}`;
  if (periodType === 'Quarterly') return `${year}Q${n}`;
  return `${year}${String(n).padStart(2, '0')}`;
}

export default function Preview() {
  const router = useRouter();
  const [types, setTypes] = useState([]);
  const [active, setActive] = useState(null);
  const [periodByType, setPeriodByType] = useState({});
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiGet('/api/py/report-types', 'Could not load the report list')
      .catch((e) => {
        if (e.status === 401) { router.push('/login'); return null; }
        throw e;
      })
      .then((body) => {
        if (!body) return;
        setTypes(body.reportTypes);
        setActive(body.reportTypes[0]?.type || null);
        const seed = {};
        body.reportTypes.forEach((t) => { seed[t.type] = t.defaultPeriod; });
        setPeriodByType(seed);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [router]);

  const current = useMemo(() => types.find((t) => t.type === active) || null, [types, active]);
  const period = current ? periodByType[current.type] : '';

  const refreshStatus = useCallback(() => {
    if (!current || !period) return;
    setStatus(null);
    apiGet(`/api/py/preview/${current.type}/status?period=${encodeURIComponent(period)}`,
           'Preview unavailable')
      .then(setStatus)
      .catch((e) => setError(e.message));
  }, [current, period]);

  useEffect(() => { setError(''); refreshStatus(); }, [refreshStatus]);

  const setPeriod = (value) => setPeriodByType((p) => ({ ...p, [current.type]: value }));
  const [year, ordinal] = current ? splitPeriod(current.periodType, period) : [0, 0];

  const ordinalOptions = () => {
    if (!current) return [];
    if (current.periodType === 'Weekly')
      return Array.from({ length: weeksInYear(year) }, (_, i) => [i + 1, `Week ${i + 1}`]);
    if (current.periodType === 'Quarterly')
      return [1, 2, 3, 4].map((q) => [q, `Q${q}`]);
    return MONTHS.map((m, i) => [i + 1, m]);
  };

  if (loading) return <><h1>Report Preview</h1><div className="card">Loading…</div></>;

  return (
    <>
      <h1>Report Preview</h1>
      <p style={{ color: 'var(--muted)', marginTop: -6 }}>
        The official eHMIS form for each report, exactly as it appears on the national instance,
        with any compiled figures in place. Read-only — available to every signed-in user, and
        available before anything is submitted to DHIS2.
      </p>

      {error && <div className="alert error">{error}</div>}

      <div className="steps" style={{ flexWrap: 'wrap' }}>
        {types.map((t) => (
          <span
            key={t.type}
            role="button"
            tabIndex={0}
            onClick={() => setActive(t.type)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setActive(t.type); }}
            className={`step ${t.type === active ? 'active' : ''}`}
            style={{ cursor: 'pointer' }}
            title={t.label}
          >
            {t.short}
          </span>
        ))}
      </div>

      {current && (
        <div className="card">
          <h2 style={{ marginBottom: 4 }}>{current.label}</h2>
          <p style={{ color: 'var(--muted)', marginTop: 0, fontSize: 13 }}>
            {current.periodType} report
            {current.compiler
              ? ' · can be compiled and submitted here'
              : ' · preview only for now, no compiler written yet'}
          </p>

          <div className="grid cols-2" style={{ maxWidth: 520 }}>
            <div>
              <label>{current.periodType === 'Weekly' ? 'Week' : current.periodType === 'Quarterly' ? 'Quarter' : 'Month'}</label>
              <select value={ordinal} onChange={(e) => setPeriod(joinPeriod(current.periodType, year, Number(e.target.value)))}>
                {ordinalOptions().map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label>Year</label>
              <input
                type="number" value={year} min="2015" max="2035"
                onChange={(e) => {
                  const y = Number(e.target.value);
                  let n = ordinal;
                  if (current.periodType === 'Weekly' && n > weeksInYear(y)) n = weeksInYear(y);
                  setPeriod(joinPeriod(current.periodType, y, n));
                }}
              />
            </div>
          </div>

          {status && (
            <div className={`alert ${status.report ? 'success' : 'info'}`} style={{ marginTop: 14 }}>
              <strong>{status.periodLabel}</strong>{' — '}
              {status.report
                ? `report #${status.report.id}, ${status.report.values} data values, compiled by ${status.report.generated_by || 'unknown'}`
                  + (status.report.push_status && status.report.push_status !== 'PENDING'
                      ? `, submission status ${status.report.push_status}.`
                      : ', not yet submitted.')
                : 'no report compiled for this period — the blank form is shown below.'}
            </div>
          )}

          <div style={{ marginTop: 14, border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden' }}>
            <iframe
              key={`${current.type}-${period}`}
              title={`${current.label} — ${period}`}
              src={`/api/py/preview/${current.type}?period=${encodeURIComponent(period)}`}
              sandbox=""
              style={{ width: '100%', height: '72vh', border: 0, background: '#fff' }}
            />
          </div>
          <p style={{ color: 'var(--muted)', fontSize: 12, marginBottom: 0 }}>
            Layout fetched from the national instance and cached. Fields are inert; nothing here
            can be edited or submitted. To print, open the frame in its own tab:&nbsp;
            <a href={`/api/py/preview/${current.type}?period=${encodeURIComponent(period)}`} target="_blank" rel="noreferrer">
              open full page
            </a>
          </p>
        </div>
      )}
    </>
  );
}
