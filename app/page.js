'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { upload as blobUpload } from '@vercel/blob/client';
import { describeError, isoWeek, isoWeekMonday, weeksInYear, weekLabel } from './lib';

const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];

/* `takes` says what file this report expects, next to the file picker. It is
   here because the report selector defaults to 105:01 and the commonest upload
   failure is not a bad file but the right file against the wrong report: a
   week-35 033B tally uploaded as July 2026 105:01, which validated as
   seventeen rows each missing a PatientNo it was never going to have. The
   server now recognises the mismatch and says so in one sentence; this says it
   before the upload rather than after. */
const REPORTS = {
  OPD:  { label: 'eHMIS 105:01 - Outpatient (OPD)',        cadence: 'monthly',
          takes: 'A patient-level extract with PatientNo, VisitDate, Age, AgeUnit, '
               + 'Sex, DiagnosisCode and VisitType, or a strata file from the '
               + 'extraction script.' },
  IPD:  { label: 'eHMIS 108 - Inpatient (IPD)',            cadence: 'monthly',
          takes: 'A patient-level extract with PatientNo, AdmissionDate, '
               + 'DischargeDate, Age, AgeUnit, Sex, Ward, DiagnosisCode and Outcome.' },
  SURV: { label: 'eHMIS 033B - Weekly Surveillance',       cadence: 'weekly',
          takes: 'A two-column tally of Code and Value, one line per indicator. '
               + 'The blank template and the weekly extraction script both write '
               + 'this shape.' },
};

/* The same week, worded for a sentence rather than a dropdown: "24 Aug -
   30 Aug 2026" reads better inside "Submit this report for …" than the ISO
   form does. Two presentations, one arithmetic - isoWeekMonday in app/lib.js,
   checked against the server for every week from 2015 to 2035. */
function weekRange(year, week) {
  const monday = isoWeekMonday(year, week);
  const sunday = new Date(monday.getTime() + 6 * 86400000);
  const fmt = (d) => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  return `${fmt(monday)} - ${fmt(sunday)} ${sunday.getUTCFullYear()}`;
}

export default function Workflow() {
  const router = useRouter();
  const now = new Date();
  const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const lastWeek = new Date(now.getTime() - 7 * 86400000);
  const [defWeekYear, defWeek] = isoWeek(lastWeek);

  const [step, setStep] = useState(0); // 0 upload, 1 validate, 2 compiled, 3 pushed
  const [reportType, setReportType] = useState('OPD');
  const [year, setYear] = useState(prev.getFullYear());
  const [month, setMonth] = useState(prev.getMonth() + 1);
  const [weekYear, setWeekYear] = useState(defWeekYear);
  const [week, setWeek] = useState(defWeek);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');
  const [upload, setUpload] = useState(null);
  const [compiled, setCompiled] = useState(null);
  const [report, setReport] = useState(null);
  const [pushResult, setPushResult] = useState(null);
  const [dryResult, setDryResult] = useState(null);
  const [source, setSource] = useState('upload');   // 'upload' | 'agent'
  const [agentInfo, setAgentInfo] = useState(null);
  const [job, setJob] = useState(null);

  useEffect(() => {
    fetch('/api/py/auth/me').then((r) => { if (!r.ok) router.push('/login'); });
  }, [router]);

  // Whether an extraction agent inside the hospital has reported in recently.
  useEffect(() => {
    let live = true;
    const poll = () => fetch('/api/py/agents')
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => { if (live && b) setAgentInfo(b); })
      .catch(() => {});
    poll();
    const t = setInterval(poll, 30000);
    return () => { live = false; clearInterval(t); };
  }, []);

  const weekly = REPORTS[reportType].cadence === 'weekly';
  // Only 105:01 has an extractor in the agent so far.
  const agentCapable = reportType === 'OPD';
  useEffect(() => {
    if (!agentCapable && source === 'agent') setSource('upload');
  }, [agentCapable, source]);
  const period = weekly ? `${weekYear}W${week}` : `${year}${String(month).padStart(2, '0')}`;
  const periodLabel = weekly
    ? `week ${week} of ${weekYear} (${weekRange(weekYear, week)})`
    : `${MONTHS[month - 1]} ${year}`;

  const doUpload = async (e) => {
    e.preventDefault();
    if (!file) return;
    if (file.size > 25 * 1024 * 1024) { setError('The file exceeds the 25 MB limit.'); return; }
    setBusy(true); setError(''); setProgress(0);
    let blob = null;
    try {
      blob = await blobUpload(`registers/${file.name}`, file, {
        access: 'private',
        handleUploadUrl: '/api/blob/upload',
        contentType: file.type || 'application/octet-stream',
        onUploadProgress: (ev) => setProgress(ev.percentage),
      });
      const r = await fetch('/api/py/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ blob_url: blob.url, filename: file.name, report_type: reportType, period }),
      });
      const text = await r.text();
      let body;
      try { body = JSON.parse(text); } catch {
        throw new Error(`Upload failed (${r.status}): ${text.slice(0, 200)}`);
      }
      if (!r.ok) throw new Error(describeError(r.status, body, 'Upload failed'));
      setUpload(body);
      setStep(1);
    } catch (err) { setError(err.message); } finally {
      setBusy(false);
      if (blob) {
        fetch('/api/blob/cleanup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: blob.url }),
        }).catch(() => {});
      }
    }
  };

  /* Ask the on-premise agent to extract this period from ClinicMaster, then
     wait for it. Nothing here touches the database: the request is queued, an
     agent inside the hospital runs it and posts back anonymous counts. */
  const doExtract = async () => {
    setBusy(true); setError(''); setJob(null);
    try {
      const r = await fetch('/api/py/extract', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ report_type: reportType, period }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(describeError(r.status, body, 'Could not queue the extraction'));
      setJob({ id: body.job_id, state: 'QUEUED', note: body.note });

      const started = Date.now();
      for (;;) {
        await new Promise((res) => setTimeout(res, 3000));
        const s = await fetch(`/api/py/extract/${body.job_id}`);
        const st = await s.json();
        if (!s.ok) throw new Error(describeError(s.status, st, 'Lost track of the extraction'));
        setJob({ id: body.job_id, state: st.state, note: st.message || body.note });
        if (st.state === 'DONE') {
          const n = st.stratum_count || 0;
          setUpload({ import_id: st.import_id, rows: n, valid_rows: n,
                      rows_in_period: n, errors: [], error_count: 0, from_agent: true });
          setStep(1);
          return;
        }
        if (st.state === 'FAILED') throw new Error(st.message || 'The extraction failed');
        if (st.state === 'EXPIRED') throw new Error('The extraction was superseded by a newer request');
        if (Date.now() - started > 10 * 60 * 1000)
          throw new Error('The extraction has not completed after ten minutes. '
            + 'Check that the agent on the hospital network is running.');
      }
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const doCompile = async () => {
    setBusy(true); setError('');
    try {
      const r = await fetch('/api/py/compile', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ import_id: upload.import_id }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(describeError(r.status, body, 'Compilation failed'));
      setCompiled(body);
      const rr = await fetch(`/api/py/reports/${body.report_id}`);
      setReport(await rr.json());
      setStep(2);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const doPush = async (dryRun = false) => {
    if (!dryRun && !confirm(`Submit this ${REPORTS[reportType].label} report for ${periodLabel} to the national DHIS2? This will write data to hmis.health.go.ug.`)) return;
    setBusy(true); setError('');
    try {
      const r = await fetch('/api/py/push', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ report_id: compiled.report_id, dry_run: dryRun }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(describeError(r.status, body, dryRun ? 'Dry run failed' : 'Submission failed'));
      if (dryRun) { setDryResult(body.result); return; }
      setPushResult(body);
      setStep(3);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const reset = () => { setStep(0); setUpload(null); setCompiled(null); setReport(null); setPushResult(null); setDryResult(null); setFile(null); setError(''); setJob(null); };

  return (
    <>
      <h1>Report Compilation</h1>
      <div className="steps">
        {['1 · Upload', '2 · Validate', '3 · Compile & Preview', '4 · Submit to DHIS2'].map((s, i) => (
          <span key={s} className={`step ${i === step ? 'active' : i < step ? 'done' : ''}`}>{s}</span>
        ))}
      </div>

      {error && <div className="alert error">{error}</div>}

      {step === 0 && (
        <form className="card" onSubmit={doUpload}>
          <h2>Upload raw data</h2>
          <p style={{ color: 'var(--muted)', marginTop: 0 }}>
            {weekly
              ? 'Provide the weekly tally as CSV or Excel with two columns, Code and Value. Leave a cell blank where the indicator was not reported; enter 0 where the true count is zero.'
              : 'Provide the register extract as CSV or Excel, following the published template.'}
            &nbsp;Download:&nbsp;
            <a href="/templates/HMIS_105_OPD_Template.csv" download>105 OPD template</a> ·&nbsp;
            <a href="/templates/HMIS_108_IPD_Template.csv" download>108 IPD template</a> ·&nbsp;
            <a href="/api/py/templates/033b">033B weekly tally</a>
          </p>
          <div className="grid cols-2">
            <div>
              <label>Report</label>
              <select value={reportType} onChange={(e) => setReportType(e.target.value)}>
                {Object.entries(REPORTS).map(([k, v]) => (
                  <option key={k} value={k}>{v.label}</option>
                ))}
              </select>
            </div>
            {weekly ? (
              <div className="grid cols-2">
                <div>
                  <label>Week</label>
                  <select value={week} onChange={(e) => setWeek(Number(e.target.value))}>
                    {Array.from({ length: weeksInYear(weekYear) }, (_, i) => i + 1).map((w) => (
                      <option key={w} value={w}>{weekLabel(weekYear, w)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label>Year</label>
                  <input type="number" value={weekYear} min="2015" max="2035"
                         onChange={(e) => {
                           const y = Number(e.target.value);
                           setWeekYear(y);
                           if (week > weeksInYear(y)) setWeek(weeksInYear(y));
                         }} />
                </div>
              </div>
            ) : (
              <div className="grid cols-2">
                <div>
                  <label>Month</label>
                  <select value={month} onChange={(e) => setMonth(Number(e.target.value))}>
                    {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label>Year</label>
                  <input type="number" value={year} min="2015" max="2035" onChange={(e) => setYear(Number(e.target.value))} />
                </div>
              </div>
            )}
          </div>
          <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 0 }}>
            Reporting period: <strong>{period}</strong> - {periodLabel}
          </p>
          <div style={{ marginTop: 16 }}>
            <label>Where should the data come from?</label>
            <div style={{ display: 'flex', gap: 18, marginTop: 4, flexWrap: 'wrap' }}>
              <label style={{ fontWeight: 400, cursor: 'pointer' }}>
                <input type="radio" name="source" checked={source === 'upload'}
                       onChange={() => setSource('upload')} />{' '}
                Upload an extract
              </label>
              <label style={{ fontWeight: 400, cursor: agentCapable ? 'pointer' : 'not-allowed',
                              opacity: agentCapable ? 1 : 0.5 }}>
                <input type="radio" name="source" checked={source === 'agent'}
                       disabled={!agentCapable}
                       onChange={() => setSource('agent')} />{' '}
                Pull from ClinicMaster
                {agentInfo && (
                  <span style={{ marginLeft: 8, fontSize: 12,
                                 color: agentInfo.online ? 'var(--ok)' : 'var(--bad)' }}>
                    ● agent {agentInfo.online ? 'online' : 'offline'}
                  </span>
                )}
              </label>
            </div>
            {!agentCapable && (
              <p style={{ color: 'var(--muted)', fontSize: 12, margin: '6px 0 0' }}>
                Direct extraction is available for 105:01 only so far; the other reports
                still need an uploaded extract.
              </p>
            )}
          </div>

          {source === 'upload' ? (
            <>
              <div style={{ marginTop: 14 }}>
                <label>Data file (.csv, .xlsx)</label>
                <input type="file" accept=".csv,.xlsx,.xls" onChange={(e) => setFile(e.target.files[0])} />
                <p style={{ color: 'var(--muted)', fontSize: 12, margin: '6px 0 0' }}>
                  {REPORTS[reportType].label.replace(/^eHMIS /, '')} takes:{' '}
                  {REPORTS[reportType].takes}
                </p>
              </div>
              <div style={{ marginTop: 18 }}>
                <button className="btn" disabled={busy || !file}>{busy ? (progress > 0 && progress < 100 ? 'Uploading… ' + Math.round(progress) + '%' : 'Processing…') : 'Upload and validate'}</button>
              </div>
            </>
          ) : (
            <>
              <p style={{ color: 'var(--muted)', fontSize: 13, marginTop: 14 }}>
                The request is queued for the extraction agent running inside the hospital.
                It runs a read-only query against ClinicMaster, aggregates on site, and returns
                counts only - no patient-level data leaves the hospital network.
              </p>
              {job && (
                <div className={`alert ${job.state === 'FAILED' ? 'error' : 'info'}`}>
                  Job #{job.id} - {job.state.toLowerCase()}
                  {job.note ? `. ${job.note}` : '.'}
                </div>
              )}
              {agentInfo && !agentInfo.online && !job && (
                <div className="alert info">
                  No agent has reported in for over three minutes. You can still queue the
                  extraction; it will run when the agent is next started.
                </div>
              )}
              <div style={{ marginTop: 14 }}>
                <button type="button" className="btn" onClick={doExtract} disabled={busy}>
                  {busy ? 'Extracting…' : `Pull ${periodLabel} from ClinicMaster`}
                </button>
              </div>
            </>
          )}
        </form>
      )}

      {step === 1 && upload && (
        <div className="card">
          <h2>Validation results</h2>
          <div className="kpis">
            <div className="kpi"><div className="n">{upload.rows}</div><div className="l">{upload.from_agent ? 'Strata received' : weekly ? 'Lines read' : 'Rows read'}</div></div>
            <div className="kpi"><div className="n">{upload.valid_rows}</div><div className="l">{upload.from_agent ? 'Accepted' : weekly ? 'Indicators accepted' : 'Valid rows'}</div></div>
            <div className="kpi"><div className="n">{upload.rows_in_period}</div><div className="l">{weekly ? 'Values reported' : `In ${periodLabel}`}</div></div>
            <div className="kpi"><div className="n" style={{ color: upload.error_count ? 'var(--bad)' : 'var(--ok)' }}>{upload.error_count}</div><div className="l">{weekly ? 'Lines with errors' : 'Rows with errors'}</div></div>
          </div>
          {/* Arithmetic the form implies but cannot enforce. Shown before the
              Compile button, because a figure that cannot be true is worth
              questioning while it is still a file rather than a submission. */}
          {upload.consistency?.length > 0 && (
            <div style={{ marginTop: 14 }}>
              {upload.consistency.map((c, i) => (
                <div key={i} className={`alert ${c.severity === 'error' ? 'error' : 'warn'}`}>
                  <b>{c.severity === 'error' ? 'Cannot be right' : 'Worth checking'}</b> - {c.message}
                </div>
              ))}
            </div>
          )}
          {upload.error_count > 0 && (
            <>
              <div className="alert info">
                {weekly
                  ? 'Lines with errors are excluded. Blank values are not errors - they simply mean the indicator was not reported this week.'
                  : 'Rows with errors are excluded from compilation. You may proceed, or correct the file and upload it again.'}
              </div>
              <table>
                <thead><tr><th>Line</th><th>{weekly ? 'Code' : 'Patient'}</th><th>Problems</th></tr></thead>
                <tbody>
                  {upload.errors.slice(0, 50).map((e) => (
                    <tr key={e.line}><td>{e.line}</td><td>{e.patient}</td><td>{e.problems.join('; ')}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <div style={{ marginTop: 18, display: 'flex', gap: 10 }}>
            <button className="btn secondary" onClick={reset}>Start again</button>
            <button className="btn" onClick={doCompile} disabled={busy || upload.rows_in_period === 0}>
              {busy ? 'Compiling…' : 'Compile report'}
            </button>
          </div>
        </div>
      )}

      {step === 2 && report && (
        <div className="card">
          {compiled?.consistency?.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              {compiled.consistency.map((c, i) => (
                <div key={i} className={`alert ${c.severity === 'error' ? 'error' : 'warn'}`}>
                  <b>{c.severity === 'error' ? 'Cannot be right' : 'Worth checking'}</b> - {c.message}
                </div>
              ))}
            </div>
          )}
          <h2>Compiled report preview - {REPORTS[reportType].label} · {periodLabel}</h2>
          <p style={{ color: 'var(--muted)', marginTop: 0 }}>Facility: {report.facility_name} · {report.compiled_data.length} data values</p>
          {compiled.unmapped?.length > 0 && (
            <div className="alert info">
              {compiled.unmapped.length} {weekly ? 'code(s)' : 'diagnosis code(s)'} could not be mapped and were excluded:&nbsp;
              {compiled.unmapped.slice(0, 12).map((u) => `${u.code} (${u.records})`).join(', ')}
            </div>
          )}
          <div style={{ maxHeight: 420, overflow: 'auto', border: '1px solid var(--line)', borderRadius: 8 }}>
            <table>
              <thead><tr><th>Data element</th><th>Disaggregation</th><th style={{ textAlign: 'right' }}>Value</th></tr></thead>
              <tbody>
                {report.compiled_data.map((v, i) => (
                  <tr key={i}>
                    <td>{v.dataElementName}</td>
                    <td>{v.categoryOptionComboName}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>{v.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {dryResult && (
            <div className={`alert ${dryResult.accepted ? 'success' : 'error'}`} style={{ marginTop: 14 }}>
              <strong>Dry run - nothing was written.</strong>{' '}
              {dryResult.accepted
                ? `DHIS2 validated all ${report.compiled_data.length} values and would accept this submission `
                  + `(imported ${dryResult.importCount?.imported ?? 0}, updated ${dryResult.importCount?.updated ?? 0}).`
                : `DHIS2 would reject or ignore this submission. ${dryResult.description || ''}`}
              {dryResult.conflicts?.length > 0 && (
                <ul style={{ marginBottom: 0 }}>
                  {dryResult.conflicts.slice(0, 8).map((c, i) => (
                    <li key={i}>{c.object}: {c.value}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <div style={{ marginTop: 18, display: 'flex', gap: 10 }}>
            <button className="btn secondary" onClick={reset}>Start again</button>
            <button className="btn secondary" onClick={() => doPush(true)} disabled={busy}>
              {busy ? 'Checking…' : 'Dry run'}
            </button>
            <button className="btn gold" onClick={() => doPush(false)} disabled={busy}>
              {busy ? 'Submitting…' : 'Submit to DHIS2'}
            </button>
          </div>
        </div>
      )}

      {step === 3 && pushResult && (
        <div className="card">
          <h2>Submission outcome</h2>
          {/* A submission that writes nothing is not a failed submission. When
              every figure is already on the server DHIS2 counts them all as
              ignored, and the API reads the period back to say so plainly, so
              the note below is worth showing on success as well as failure. */}
          <div className={`alert ${pushResult.push_status === 'PUSHED' ? 'success' : 'error'}`}>
            {pushResult.push_status === 'PUSHED'
              ? 'The report was accepted by the national DHIS2 instance.'
              : `Submission failed: ${pushResult.result?.description || 'see details below'}`}
            {pushResult.push_status === 'PUSHED' && pushResult.result?.description
              && !/^import process completed/i.test(pushResult.result.description) && (
              <div style={{ marginTop: 8 }}>{pushResult.result.description}</div>
            )}
          </div>
          {pushResult.result?.verification?.unaccounted > 0 && (
            <table>
              <thead><tr><th>Data element</th><th>Sent</th><th>On the server</th></tr></thead>
              <tbody>
                {[...(pushResult.result.verification.differing || []),
                  ...(pushResult.result.verification.missing || [])].slice(0, 20).map((v, i) => (
                  <tr key={i}>
                    <td>{v.dataElementName || v.dataElement}</td>
                    <td style={{ textAlign: 'right' }}>{v.value}</td>
                    <td style={{ textAlign: 'right' }}>{v.onServer ?? 'nothing'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="kpis">
            {['imported', 'updated', 'ignored', 'deleted'].map((k) => (
              <div className="kpi" key={k}>
                <div className="n">{pushResult.result?.importCount?.[k] ?? '-'}</div>
                <div className="l">{k}</div>
              </div>
            ))}
          </div>
          {pushResult.result?.conflicts?.length > 0 && (
            <table>
              <thead><tr><th>Object</th><th>Conflict</th></tr></thead>
              <tbody>
                {pushResult.result.conflicts.map((c, i) => (
                  <tr key={i}><td>{c.object}</td><td>{c.value}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          <div style={{ marginTop: 18 }}>
            <button className="btn" onClick={reset}>Compile another report</button>
          </div>
        </div>
      )}
    </>
  );
}
