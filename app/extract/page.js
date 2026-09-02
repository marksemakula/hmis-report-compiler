'use client';
import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiGet, weeksInYear, weekLabel } from '../lib';

const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];




function splitPeriod(periodType, period) {
  const p = String(period || '');
  if (periodType === 'Weekly')    { const m = p.match(/^(\d{4})W(\d{1,2})$/i); return m ? [+m[1], +m[2]] : [2026, 1]; }
  if (periodType === 'Quarterly') { const m = p.match(/^(\d{4})Q([1-4])$/i);   return m ? [+m[1], +m[2]] : [2026, 1]; }
  const m = p.match(/^(\d{4})(\d{2})$/); return m ? [+m[1], +m[2]] : [2026, 1];
}
function joinPeriod(periodType, year, n) {
  if (periodType === 'Weekly')    return `${year}W${n}`;
  if (periodType === 'Quarterly') return `${year}Q${n}`;
  return `${year}${String(n).padStart(2, '0')}`;
}

export default function ExtractScripts() {
  const router = useRouter();
  const [types, setTypes] = useState([]);
  const [options, setOptions] = useState(null);
  const [osKey, setOsKey] = useState('windows');
  const [report, setReport] = useState('OPD');
  const [period, setPeriod] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiGet('/api/py/report-types', 'Could not load the report list'),
      apiGet('/api/py/scripts', 'Could not load the script options'),
    ])
      .then(([t, o]) => {
        setTypes(t.reportTypes);
        setOptions(o);
        const first = t.reportTypes.find((r) => o.reports.includes(r.type));
        if (first) { setReport(first.type); setPeriod(first.defaultPeriod); }
      })
      .catch((e) => { if (e.status === 401) router.push('/login'); else setError(e.message); })
      .finally(() => setLoading(false));
  }, [router]);

  const current = useMemo(() => types.find((t) => t.type === report) || null, [types, report]);
  const currentStatus = useMemo(
    () => (options?.reportStatus || []).find((r) => r.type === report) || null,
    [options, report]);
  const canDownload = !currentStatus || currentStatus.available;
  const [year, ordinal] = current ? splitPeriod(current.periodType, period) : [0, 0];

  const ordinalOptions = () => {
    if (!current) return [];
    if (current.periodType === 'Weekly')
      return Array.from({ length: weeksInYear(year) }, (_, i) => [i + 1, weekLabel(year, i + 1)]);
    if (current.periodType === 'Quarterly') return [1, 2, 3, 4].map((q) => [q, `Q${q}`]);
    return MONTHS.map((m, i) => [i + 1, m]);
  };

  const href = current && period
    ? `/api/py/scripts/${report}?period=${encodeURIComponent(period)}&os=${osKey}`
    : null;
  const runtime = options?.operatingSystems?.find((o) => o.key === osKey)?.runtime || '';

  if (loading) return <><h1>Extraction Scripts</h1><div className="card">Loading…</div></>;

  return (
    <>
      <h1>Extraction Scripts</h1>
      <p style={{ color: 'var(--muted)', marginTop: -6 }}>
        The compiler cannot reach ClinicMaster from the internet. Download a script here,
        run it on a machine connected to the hospital network, then upload the file it
        writes on the Compile page.
      </p>

      {error && <div className="alert error">{error}</div>}

      <div className="card">
        <h2>1 · Which machine will you run it on?</h2>
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginTop: 6 }}>
          {(options?.operatingSystems || []).map((o) => (
            <label key={o.key} style={{ fontWeight: 400, cursor: 'pointer' }}>
              <input type="radio" name="os" checked={osKey === o.key}
                     onChange={() => setOsKey(o.key)} />{' '}
              {o.label}
              <span style={{ color: 'var(--muted)', fontSize: 12 }}> · {o.runtime}</span>
            </label>
          ))}
        </div>
        {osKey === 'windows' && (
          <p style={{ color: 'var(--muted)', fontSize: 12.5, marginBottom: 0 }}>
            PowerShell queries SQL Server through .NET, so nothing needs installing.
          </p>
        )}
        {osKey === 'sql' && (
          <p style={{ color: 'var(--muted)', fontSize: 12.5, marginBottom: 0 }}>
            A plain .sql file for a client you already have open. Nothing to install,
            no interpreter, no driver. Run it, then save the results grid as CSV.
          </p>
        )}
        {(osKey === 'macos' || osKey === 'linux') && (
          <p style={{ color: 'var(--muted)', fontSize: 12.5, marginBottom: 0 }}>
            Needs Python 3 and a driver: <code>pip3 install pymssql</code>. If that
            will not install, choose <strong>SQL only</strong> instead - it needs
            neither.
          </p>
        )}
      </div>

      <div className="card">
        <h2>2 · Which report and period?</h2>
        <div className="grid cols-2">
          <div>
            <label>Report</label>
            {/* All eight reports are listed. The ones without a script are
                disabled and carry their reason below, because a report that is
                simply absent reads as a fault in the app rather than as work
                not yet done. */}
            <select value={report} onChange={(e) => {
              const t = types.find((x) => x.type === e.target.value);
              setReport(e.target.value);
              if (t) setPeriod(t.defaultPeriod);
            }}>
              <optgroup label="Script available">
                {(options?.reportStatus || []).filter((r) => r.available).map((r) => (
                  <option key={r.type} value={r.type}>
                    {r.label} · {r.periodType.toLowerCase()}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Not yet - upload only">
                {(options?.reportStatus || []).filter((r) => !r.available).map((r) => (
                  <option key={r.type} value={r.type} disabled>
                    {r.label} · {r.periodType.toLowerCase()}
                  </option>
                ))}
              </optgroup>
            </select>
            {currentStatus && !currentStatus.available && (
              <p style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 6 }}>
                {currentStatus.reason}
              </p>
            )}
          </div>
          {current && (
            <div className="grid cols-2">
              <div>
                <label>{current.periodType === 'Weekly' ? 'Week'
                       : current.periodType === 'Quarterly' ? 'Quarter' : 'Month'}</label>
                <select value={ordinal}
                        onChange={(e) => setPeriod(joinPeriod(current.periodType, year, Number(e.target.value)))}>
                  {ordinalOptions().map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </div>
              <div>
                <label>Year</label>
                <input type="number" value={year} min="2015" max="2035"
                       onChange={(e) => setPeriod(joinPeriod(current.periodType, Number(e.target.value), ordinal))} />
              </div>
            </div>
          )}
        </div>
        {current && canDownload && (
          <p style={{ color: 'var(--muted)', fontSize: 12.5, marginBottom: 0 }}>
            {current.periodType === 'Weekly'
              ? 'Weeks run Monday to Sunday on the ISO-8601 calendar, the same rule DHIS2 uses.'
              : current.periodType === 'Quarterly'
              ? 'Quarters follow the calendar year: Q1 is January to March.'
              : 'Months are calendar months.'}{' '}
            The period is written into the query, so a script downloaded for one
            period cannot be run against another.
          </p>
        )}
      </div>

      <div className="card">
        <h2>Understanding the database</h2>
        <p style={{ color: 'var(--muted)', marginTop: 0 }}>
          Two read-only scripts that describe ClinicMaster rather than extract a report.
          Run either on the hospital network and send the file back; they return
          reference data only - table columns, lookup values, the disease dictionary -
          and read no patient row.
        </p>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {(options?.utilities || []).map((u) => (
            <a key={u.key} className="btn secondary"
               href={`/api/py/scripts/${u.key}?os=${osKey}`} download
               title={u.note}>
              {u.label}
            </a>
          ))}
        </div>
        {(options?.utilities || []).map((u) => (
          <p key={u.key} style={{ color: 'var(--muted)', fontSize: 12.5, margin: '8px 0 0' }}>
            <strong>{u.label}</strong> - {u.note}
          </p>
        ))}
      </div>

      <div className="card">
        <h2>3 · Download and run</h2>
        <p style={{ color: 'var(--muted)', marginTop: 0 }}>
          The period is written into the script, so it cannot be run against the wrong
          period by accident. It aggregates before it writes: {report === 'SURV'
            ? 'the file contains one line per indicator code - a count, and nothing else.'
            : 'the file contains counts by age band, sex and visit type - no patient names, numbers or dates of birth.'}
        </p>
        {href && canDownload && (
          <a className="btn" href={href} download>
            Download {runtime} script for {current?.short} · {current?.periodType === 'Weekly' ? weekLabel(year, ordinal) : period}
          </a>
        )}
        {!canDownload && (
          <div className="alert info" style={{ marginTop: 0 }}>
            No script for {current?.short} yet. {currentStatus?.reason} Until there is
            one, compile this report by uploading an extract on the Compile page.
          </div>
        )}
        <div style={{ marginTop: 18, fontSize: 13.5 }}>
          <strong>Then, on the hospital network:</strong>
          {osKey === 'sql' ? (
            <>
              <ol style={{ marginTop: 8, paddingLeft: 20 }}>
                <li>Open the downloaded <code>.sql</code> file in Azure Data Studio,
                    connected to {options?.server || '172.20.0.230'}.</li>
                <li>Run it. It returns one grid.</li>
                <li>Right-click the grid, <strong>Save as CSV</strong>, and give the file
                    its own name - Azure Data Studio reuses <code>Results.csv</code>,
                    which is how a stale file gets uploaded twice.</li>
                <li>Upload that CSV on the Compile page, choosing the same report
                    and period.</li>
              </ol>
              The columns come back ready to upload; nothing needs renaming.
            </>
          ) : (
            <>
              <pre style={{ background: 'var(--pale, #E8F1F1)', padding: 12, borderRadius: 8,
                            overflowX: 'auto', marginTop: 8 }}>
{osKey === 'windows'
  ? `.\\jrrh_extract_${report.toLowerCase()}_${period}.ps1 -User readonly_user`
  : `python3 jrrh_extract_${report.toLowerCase()}_${period}.py --user readonly_user`}
              </pre>
              It asks for the password, writes <code>JRRH_{report}_{period}_strata.csv</code>,
              and tells you how many visits it found. Upload that file on the Compile page,
              choosing the same report and period. Leave <code>--user</code> off and it
              will ask for the login too.
            </>
          )}
        </div>
        <div className="alert info" style={{ marginTop: 16 }}>
          You need a <strong>read-only</strong> SQL login on ClinicMaster. Do not use an
          account with write rights - the script only ever reads, but a read-only account
          means the question never arises.
        </div>
      </div>
    </>
  );
}
