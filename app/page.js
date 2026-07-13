'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { upload as blobUpload } from '@vercel/blob/client';

const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];

export default function Workflow() {
  const router = useRouter();
  const now = new Date();
  const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);

  const [step, setStep] = useState(0); // 0 upload, 1 validate, 2 compiled, 3 pushed
  const [reportType, setReportType] = useState('OPD');
  const [year, setYear] = useState(prev.getFullYear());
  const [month, setMonth] = useState(prev.getMonth() + 1);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');
  const [upload, setUpload] = useState(null);
  const [compiled, setCompiled] = useState(null);
  const [report, setReport] = useState(null);
  const [pushResult, setPushResult] = useState(null);

  useEffect(() => {
    fetch('/api/py/auth/me').then((r) => { if (!r.ok) router.push('/login'); });
  }, [router]);

  const period = `${year}${String(month).padStart(2, '0')}`;

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
      if (!r.ok) throw new Error(body.detail || body.error || 'Upload failed');
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

  const doCompile = async () => {
    setBusy(true); setError('');
    try {
      const r = await fetch('/api/py/compile', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ import_id: upload.import_id }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || 'Compilation failed');
      setCompiled(body);
      const rr = await fetch(`/api/py/reports/${body.report_id}`);
      setReport(await rr.json());
      setStep(2);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const doPush = async () => {
    if (!confirm(`Submit this ${reportType} report for ${MONTHS[month - 1]} ${year} to the national DHIS2? This will write data to hmis.health.go.ug.`)) return;
    setBusy(true); setError('');
    try {
      const r = await fetch('/api/py/push', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ report_id: compiled.report_id }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || 'Submission failed');
      setPushResult(body);
      setStep(3);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const reset = () => { setStep(0); setUpload(null); setCompiled(null); setReport(null); setPushResult(null); setFile(null); setError(''); };

  return (
    <>
      <h1>Monthly Report Compilation</h1>
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
            Provide the register extract as CSV or Excel, following the published template. Download:&nbsp;
            <a href="/templates/HMIS_105_OPD_Template.csv" download>105 OPD template</a> ·&nbsp;
            <a href="/templates/HMIS_108_IPD_Template.csv" download>108 IPD template</a>
          </p>
          <div className="grid cols-2">
            <div>
              <label>Report</label>
              <select value={reportType} onChange={(e) => setReportType(e.target.value)}>
                <option value="OPD">eHMIS 105:01 — Outpatient (OPD)</option>
                <option value="IPD">eHMIS 108 — Inpatient (IPD)</option>
              </select>
            </div>
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
          </div>
          <div style={{ marginTop: 14 }}>
            <label>Data file (.csv, .xlsx)</label>
            <input type="file" accept=".csv,.xlsx,.xls" onChange={(e) => setFile(e.target.files[0])} required />
          </div>
          <div style={{ marginTop: 18 }}>
            <button className="btn" disabled={busy || !file}>{busy ? (progress > 0 && progress < 100 ? 'Uploading… ' + Math.round(progress) + '%' : 'Processing…') : 'Upload and validate'}</button>
          </div>
        </form>
      )}

      {step === 1 && upload && (
        <div className="card">
          <h2>Validation results</h2>
          <div className="kpis">
            <div className="kpi"><div className="n">{upload.rows}</div><div className="l">Rows read</div></div>
            <div className="kpi"><div className="n">{upload.valid_rows}</div><div className="l">Valid rows</div></div>
            <div className="kpi"><div className="n">{upload.rows_in_period}</div><div className="l">In {MONTHS[month-1]} {year}</div></div>
            <div className="kpi"><div className="n" style={{ color: upload.error_count ? 'var(--bad)' : 'var(--ok)' }}>{upload.error_count}</div><div className="l">Rows with errors</div></div>
          </div>
          {upload.error_count > 0 && (
            <>
              <div className="alert info">Rows with errors are excluded from compilation. You may proceed, or correct the file and upload it again.</div>
              <table>
                <thead><tr><th>Line</th><th>Patient</th><th>Problems</th></tr></thead>
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
          <h2>Compiled report preview — {reportType === 'OPD' ? 'eHMIS 105:01' : 'eHMIS 108'} · {MONTHS[month-1]} {year}</h2>
          <p style={{ color: 'var(--muted)', marginTop: 0 }}>Facility: {report.facility_name} · {report.compiled_data.length} data values</p>
          {compiled.unmapped?.length > 0 && (
            <div className="alert info">
              {compiled.unmapped.length} diagnosis code(s) could not be mapped and were excluded:&nbsp;
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
          <div style={{ marginTop: 18, display: 'flex', gap: 10 }}>
            <button className="btn secondary" onClick={reset}>Start again</button>
            <button className="btn gold" onClick={doPush} disabled={busy}>
              {busy ? 'Submitting…' : 'Submit to DHIS2'}
            </button>
          </div>
        </div>
      )}

      {step === 3 && pushResult && (
        <div className="card">
          <h2>Submission outcome</h2>
          <div className={`alert ${pushResult.push_status === 'PUSHED' ? 'success' : 'error'}`}>
            {pushResult.push_status === 'PUSHED'
              ? 'The report was accepted by the national DHIS2 instance.'
              : `Submission failed: ${pushResult.result?.description || 'see details below'}`}
          </div>
          <div className="kpis">
            {['imported', 'updated', 'ignored', 'deleted'].map((k) => (
              <div className="kpi" key={k}>
                <div className="n">{pushResult.result?.importCount?.[k] ?? '—'}</div>
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
