'use client';
/* Clinical Audits - the Adult ART, PMTCT and EID service-gap audits.
 *
 * Everything on this page runs in the browser. A line list is patient-level
 * data - ART numbers, dates of birth, CHW phone numbers - and this
 * application's rule is that no patient row reaches the server (see
 * agent/README.md). So the file is read here, audited here by
 * app/auditrules.js, and the worklist is downloaded from here. The only
 * server call is the sign-in check and, for data officers, the read-only
 * schema script, which carries no patient data in either direction.
 */
import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  TOOLS, TOOL_ORDER, CODES, audit, mapHeaders, parseCSV, toRecords, detectDateOrder,
  exportLineList, exportWorklist, templateCSV, worklist,
} from '../auditrules';

const TINT = {
  adult: { fg: 'var(--ss-blue)', bg: '#e6edf6' },
  pmtct: { fg: 'var(--ss-purple)', bg: '#f1e8f3' },
  eid: { fg: 'var(--ss-amber)', bg: '#f7efdc' },
};
const CODE_BADGE = { Y: 'bad', N: 'ok', ON: 'info', NE: 'muted', NA: 'muted' };
const WORKLIST_PAGE = 100;

const todayISO = () => new Date().toISOString().slice(0, 10);

function download(name, text) {
  const blob = new Blob([`﻿${text}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Coverage({ value }) {
  if (value === null || value === undefined) return <span style={{ color: 'var(--muted)' }}>-</span>;
  const tone = value >= 90 ? 'success' : value >= 70 ? 'warning' : 'danger';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 140 }}>
      <div className="progress" style={{ flex: 1 }}>
        <div className={`progress-bar ${tone}`} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
      <span style={{ fontVariantNumeric: 'tabular-nums', minWidth: 44, textAlign: 'right' }}>{value}%</span>
    </div>
  );
}

export default function ClinicalAudits() {
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [toolKey, setToolKey] = useState('adult');
  const [osKey, setOsKey] = useState('sql');
  const [file, setFile] = useState(null); // { name, rows }
  const [refDate, setRefDate] = useState(todayISO());
  const [order, setOrder] = useState('auto');
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [serviceFilter, setServiceFilter] = useState('');
  const [shown, setShown] = useState(WORKLIST_PAGE);

  const tool = TOOLS[toolKey];

  useEffect(() => {
    fetch('/api/py/auth/me')
      .then((r) => {
        if (r.status === 401) { router.push('/login'); return null; }
        return r.ok ? r.json() : null;
      })
      .then(setUser)
      .catch(() => setUser(null));
  }, [router]);

  // A different tool means a different sheet: the loaded file is dropped
  // rather than reinterpreted under another tool's columns.
  const pickTool = (k) => {
    setToolKey(k);
    setFile(null);
    setError('');
    setSearch('');
    setServiceFilter('');
    setShown(WORKLIST_PAGE);
  };

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    setError('');
    if (!f) return;
    if (/\.xlsx?$|\.xlsm$/i.test(f.name)) {
      setError('That is an Excel workbook. Open it, go to the audit sheet, and use File > Save As > '
        + 'CSV UTF-8 (this saves only that sheet). Then load the CSV here. The workbooks are 30-70 MB '
        + 'of formulas; the sheet alone is a few hundred kilobytes.');
      return;
    }
    try {
      const text = await f.text();
      const rows = parseCSV(text);
      if (rows.length < 2) throw new Error('The file has a header row but no clients.');
      setFile({ name: f.name, rows });
      setShown(WORKLIST_PAGE);
    } catch (err) {
      setError(`Could not read ${f.name}: ${err.message}`);
    }
  };

  const mapping = useMemo(() => (file ? mapHeaders(tool, file.rows[0]) : null), [file, tool]);
  const records = useMemo(
    () => (file && mapping ? toRecords(tool, file.rows.slice(1), mapping.map) : []),
    [file, mapping, tool],
  );
  const detected = useMemo(() => detectDateOrder(records,
    tool.fields.filter((f) => f.type === 'date').map((f) => f.key)), [records, tool]);
  const result = useMemo(() => {
    if (!records.length) return null;
    return audit(tool, records, { ref: refDate, order: order === 'auto' ? detected.order : order });
  }, [records, tool, refDate, order, detected]);

  const label = useMemo(() => Object.fromEntries(tool.services.map((s) => [s.key, s.label])), [tool]);
  const work = useMemo(() => (result ? worklist(tool, result) : []), [result, tool]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return work.filter((r) => (!serviceFilter || r.flags[serviceFilter] === 'Y')
      && (!q || String(r.input[tool.idField] || r.input.mother_id || '').toLowerCase().includes(q)
        || String(r.input.chw || '').toLowerCase().includes(q)));
  }, [work, search, serviceFilter, tool]);

  const matched = mapping ? tool.fields.length - mapping.missing.length : 0;
  const fieldLabel = (k) => tool.fields.find((f) => f.key === k)?.header || k;
  const stamp = `${tool.key}_${result?.ref || refDate}`;
  const canScript = user && user.role !== 'viewer';
  const owedNone = result?.summary.cohort.find((c) => c.label === 'In care and owed no service');
  const totalGaps = result ? result.summary.cascades.reduce((n, c) => n + c.outstanding, 0) : 0;

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-pretitle" style={{ color: 'var(--ss-accent)' }}>Quality improvement</div>
          <h1 className="page-title" style={{ fontSize: '1.75rem', lineHeight: '2.25rem' }}>Clinical audits</h1>
          <p style={{ color: 'var(--muted)', margin: '.25rem 0 0', maxWidth: 760 }}>
            The Ministry&apos;s Adult ART, PMTCT and EID audit tools, run without the workbooks. Load a
            client line list and see, for every client, which services are still owed - then take the
            worklist to the clinic.
          </p>
        </div>
      </div>

      <div className="alert info" style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <span aria-hidden="true" style={{ fontWeight: 700 }}>&#9432;</span>
        <span>
          <strong>Nothing you load here leaves this computer.</strong> The line list is read and audited
          inside your browser; no client row is sent to the server, stored, or logged. Close the tab and
          it is gone.
        </span>
      </div>

      <div className="grid cols-3" style={{ marginBottom: 'var(--tblr-page-padding)' }}>
        {TOOL_ORDER.map((k) => {
          const t = TOOLS[k];
          const active = k === toolKey;
          return (
            <button
              key={k}
              type="button"
              onClick={() => pickTool(k)}
              className="card"
              aria-pressed={active}
              style={{
                textAlign: 'left', cursor: 'pointer', font: 'inherit', color: 'inherit', margin: 0,
                borderColor: active ? 'var(--ss-accent)' : undefined,
                boxShadow: active ? '0 0 0 2px rgba(20,108,89,.18)' : undefined,
              }}
            >
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8 }}>
                <span style={{
                  width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center',
                  background: TINT[k].bg, color: TINT[k].fg, fontWeight: 700, fontSize: 13,
                }}
                >
                  {t.short.slice(0, 2).toUpperCase()}
                </span>
                <strong style={{ fontSize: '1rem' }}>{t.label}</strong>
                {active && <span className="badge pill" style={{ marginLeft: 'auto', background: 'var(--ss-gold)', color: 'var(--ss-green)' }}>Selected</span>}
              </div>
              <span style={{ color: 'var(--muted)', fontSize: 13 }}>{t.population}</span>
              <span style={{ display: 'block', marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
                {t.services.length} services audited · workbook sheet &ldquo;{t.sheet}&rdquo;
              </span>
            </button>
          );
        })}
      </div>

      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <div className="card">
          <h2 style={{ fontSize: '1.05rem' }}>1 · Get the line list</h2>
          <p style={{ color: 'var(--muted)', marginTop: 0 }}>
            <strong>From a filled workbook.</strong> Open the {tool.short} audit workbook, go to the
            &ldquo;{tool.sheet}&rdquo; sheet and save it as <em>CSV UTF-8</em>. The columns are recognised
            by their own headings, including the ones the sheet repeats.
          </p>
          <p style={{ color: 'var(--muted)' }}>
            <strong>By hand.</strong> Start from a blank sheet with the tool&apos;s entry columns - the
            computed columns are left out, because this page computes them.
          </p>
          <button type="button" className="btn secondary" style={{ alignSelf: 'flex-start' }} onClick={() => download(`${tool.key}_audit_template.csv`, templateCSV(tool))}>
            Blank {tool.short} template (CSV)
          </button>

          <hr />
          <p style={{ color: 'var(--muted)', marginBottom: 8 }}>
            <strong>From ClinicMaster.</strong> The ART, PMTCT and EID tables behind these audits have not
            been confirmed yet, and a query written against guessed columns is how earlier extracts
            failed. The first step is a read-only schema script: it lists the HIV clinic&apos;s tables,
            columns and test codes, and reads no patient row. Send its output back and the extraction
            query that fills this line list will be written against the real columns.
          </p>
          {canScript ? (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <select value={osKey} onChange={(e) => setOsKey(e.target.value)} aria-label="Script type" style={{ width: 'auto' }}>
                <option value="sql">SQL only (Azure Data Studio)</option>
                <option value="windows">Windows (PowerShell)</option>
                <option value="macos">macOS (Python)</option>
                <option value="linux">Linux (Python)</option>
              </select>
              <a className="btn" href={`/api/py/scripts/hivcare?os=${osKey}`} download>
                Download HIV care schema script
              </a>
            </div>
          ) : (
            <div className="alert warn" style={{ margin: 0 }}>
              Schema scripts are for data officers. Ask one to run it.
            </div>
          )}
          <p style={{ color: 'var(--muted)', fontSize: 12.5, margin: '8px 0 0' }}>
            Status: <span className="badge warn">Awaiting schema</span> - the auto-fill extract follows once the
            schema output is back.
          </p>
        </div>

        <div className="card">
          <h2 style={{ fontSize: '1.05rem' }}>2 · Load and audit</h2>
          <label style={{ display: 'block', marginBottom: 12 }}>
            <span style={{ display: 'block', fontWeight: 500, marginBottom: 4 }}>{tool.short} line list (CSV)</span>
            <input type="file" accept=".csv,text/csv,.xlsx,.xls" onChange={onFile} />
          </label>
          <div className="grid cols-2" style={{ gap: 12 }}>
            <label>
              <span style={{ display: 'block', fontWeight: 500, marginBottom: 4 }}>Audit date</span>
              <input type="date" value={refDate} max={todayISO()} onChange={(e) => setRefDate(e.target.value || todayISO())} />
              <span style={{ display: 'block', fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                What &ldquo;today&rdquo; means for due dates. The workbooks use the day they are opened, so last
                month&apos;s audit could never be reproduced; here it is fixed.
              </span>
            </label>
            <label>
              <span style={{ display: 'block', fontWeight: 500, marginBottom: 4 }}>Dates written as</span>
              <select value={order} onChange={(e) => setOrder(e.target.value)}>
                <option value="auto">Detect ({detected.order === 'MDY' ? 'month first' : 'day first'})</option>
                <option value="DMY">Day first - 25/01/2026</option>
                <option value="MDY">Month first - 01/25/2026</option>
              </select>
              {file && <span style={{ display: 'block', fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>{detected.evidence}.</span>}
            </label>
          </div>
          {error && <div className="alert error" style={{ marginTop: 12 }}>{error}</div>}
          {file && mapping && (
            <div style={{ marginTop: 12, fontSize: 13 }}>
              <div>
                <strong>{file.name}</strong> · {records.length.toLocaleString('en-GB')} clients
                {file.rows.length - 1 > records.length && (
                  <span style={{ color: 'var(--muted)' }}> ({(file.rows.length - 1 - records.length).toLocaleString('en-GB')} rows without a client number skipped)</span>
                )}
              </div>
              <div style={{ marginTop: 4 }}>
                <span className={`badge ${mapping.missing.length === 0 ? 'ok' : matched > tool.fields.length / 2 ? 'warn' : 'bad'}`}>
                  {matched} of {tool.fields.length} columns recognised
                </span>
              </div>
              {mapping.missing.length > 0 && (
                <details style={{ marginTop: 6 }}>
                  <summary style={{ cursor: 'pointer' }}>Not found ({mapping.missing.length}) - services that need these read as outstanding or not applicable</summary>
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18, color: 'var(--muted)' }}>
                    {mapping.missing.map((k) => <li key={k}>{fieldLabel(k)}</li>)}
                  </ul>
                </details>
              )}
              {records.length === 0 && (
                <div className="alert warn" style={{ marginTop: 8 }}>
                  No row has a client number. Check that this is the {tool.short} sheet, not another tool&apos;s.
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {result && (
        <>
          <div className="kpis">
            <div className="kpi"><div className="n">{records.length.toLocaleString('en-GB')}</div><div className="l">Clients on the list</div></div>
            <div className="kpi"><div className="n">{result.summary.inCare.toLocaleString('en-GB')}</div><div className="l">In care</div></div>
            <div className="kpi"><div className="n">{owedNone?.pct ?? 0}%</div><div className="l">In care, owed nothing</div></div>
            <div className="kpi"><div className="n" style={{ color: 'var(--bad)' }}>{totalGaps.toLocaleString('en-GB')}</div><div className="l">Services outstanding</div></div>
            <div className="kpi"><div className="n">{work.length.toLocaleString('en-GB')}</div><div className="l">Clients on the worklist</div></div>
          </div>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 'var(--tblr-page-padding)' }}>
            <button type="button" className="btn" onClick={() => download(`${stamp}_worklist.csv`, exportWorklist(tool, result))}>
              Download worklist (CSV)
            </button>
            <button type="button" className="btn secondary" onClick={() => download(`${stamp}_audited_line_list.csv`, exportLineList(tool, result))}>
              Download audited line list (CSV)
            </button>
            <span style={{ alignSelf: 'center', color: 'var(--muted)', fontSize: 12.5 }}>
              Both contain client identifiers. Keep them on hospital machines.
            </span>
          </div>

          <div className="grid cols-2" style={{ alignItems: 'start' }}>
            <div className="card flush">
              <div className="card-header"><h3 className="card-title">Cohort</h3>
                <span className="card-actions" style={{ color: 'var(--muted)', fontSize: 12 }}>as at {result.ref}</span>
              </div>
              <table className="card-table">
                <tbody>
                  {result.summary.cohort.map((c) => (
                    <tr key={c.label}>
                      <td style={{ paddingLeft: c.indent ? 36 : undefined, color: c.indent ? 'var(--muted)' : undefined }}>{c.label}</td>
                      <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{c.n.toLocaleString('en-GB')}</td>
                      <td style={{ textAlign: 'right', color: 'var(--muted)', fontVariantNumeric: 'tabular-nums', width: 70 }}>
                        {c.pct === null ? '' : `${c.pct}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="card flush">
              <div className="card-header"><h3 className="card-title">Services among clients in care</h3></div>
              <div className="scroll-x">
                <table className="card-table">
                  <thead>
                    <tr><th>Service</th><th style={{ textAlign: 'right' }}>Eligible</th><th style={{ textAlign: 'right' }}>Owed</th><th>Coverage</th></tr>
                  </thead>
                  <tbody>
                    {result.summary.cascades.map((c) => (
                      <tr key={c.key}>
                        <td>
                          <button type="button" className="btn ghost sm" style={{ padding: 0, color: 'inherit', textAlign: 'left' }}
                            onClick={() => { setServiceFilter(c.outstanding ? c.key : ''); setShown(WORKLIST_PAGE); document.getElementById('worklist')?.scrollIntoView({ behavior: 'smooth' }); }}
                            title={c.outstanding ? 'Show these clients in the worklist' : undefined}
                          >
                            {c.label}
                          </button>
                        </td>
                        <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{c.eligible.toLocaleString('en-GB')}</td>
                        <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: c.outstanding ? 'var(--bad)' : undefined, fontWeight: c.outstanding ? 600 : undefined }}>
                          {c.outstanding.toLocaleString('en-GB')}
                        </td>
                        <td><Coverage value={c.coverage} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {result.summary.eid && (
            <div className="card flush">
              <div className="card-header"><h3 className="card-title">EID programme indicators</h3>
                <span className="card-actions" style={{ color: 'var(--muted)', fontSize: 12 }}>infant age on the audit date</span>
              </div>
              <table className="card-table">
                <thead><tr><th>Indicator</th><th style={{ textAlign: 'right' }}>Numerator</th><th style={{ textAlign: 'right' }}>Denominator</th><th>Proportion</th></tr></thead>
                <tbody>
                  {result.summary.eid.map((x) => (
                    <tr key={x.label}>
                      <td>{x.label}</td>
                      <td style={{ textAlign: 'right' }}>{x.num}</td>
                      <td style={{ textAlign: 'right' }}>{x.den}</td>
                      <td><Coverage value={x.pct} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="card flush" id="worklist">
            <div className="card-header" style={{ flexWrap: 'wrap' }}>
              <h3 className="card-title">Worklist</h3>
              <span style={{ color: 'var(--muted)', fontSize: 12.5 }}>
                Clients in care owed at least one service, most owed first
              </span>
              <div className="card-actions" style={{ flexWrap: 'wrap' }}>
                <select value={serviceFilter} onChange={(e) => { setServiceFilter(e.target.value); setShown(WORKLIST_PAGE); }} aria-label="Filter by service" style={{ width: 'auto', maxWidth: 280 }}>
                  <option value="">Every service</option>
                  {result.summary.cascades.filter((c) => c.outstanding).map((c) => (
                    <option key={c.key} value={c.key}>{c.label} ({c.outstanding})</option>
                  ))}
                </select>
                <input type="search" placeholder="Client number or CHW" value={search}
                  onChange={(e) => { setSearch(e.target.value); setShown(WORKLIST_PAGE); }} style={{ width: 200 }} />
              </div>
            </div>
            {filtered.length === 0 ? (
              <div className="card-body" style={{ color: 'var(--muted)' }}>
                {work.length === 0 ? 'Every client in care has received every service they are eligible for.' : 'No client matches.'}
              </div>
            ) : (
              <div className="scroll-x">
                <table className="card-table">
                  <thead>
                    <tr>
                      <th>{tool.key === 'eid' ? 'EID no.' : 'Client no.'}</th>
                      <th>Status</th><th>Next appointment</th><th>CHW</th><th style={{ textAlign: 'right' }}>Owed</th><th>Services owed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.slice(0, shown).map((r, i) => (
                      <tr key={`${r.input[tool.idField]}-${i}`}>
                        <td style={{ whiteSpace: 'nowrap', fontWeight: 500 }}>{r.input[tool.idField] || r.input.mother_id}</td>
                        <td style={{ whiteSpace: 'nowrap' }}>{r.derived.status || '-'}</td>
                        <td style={{ whiteSpace: 'nowrap' }}>{r.input.next_appt || '-'}</td>
                        <td>{r.input.chw || <span className="badge bad">None</span>}</td>
                        <td style={{ textAlign: 'right', fontWeight: 600 }}>{r.outstanding.length}</td>
                        <td>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                            {r.outstanding.map((k) => <span key={k} className={`badge ${k === serviceFilter ? 'bad' : 'warn'}`}>{label[k]}</span>)}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {filtered.length > shown && (
              <div className="card-footer" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                Showing {shown.toLocaleString('en-GB')} of {filtered.length.toLocaleString('en-GB')}.
                <button type="button" className="btn secondary sm" onClick={() => setShown((n) => n + WORKLIST_PAGE * 5)}>Show more</button>
                <span>The downloaded worklist has every client.</span>
              </div>
            )}
          </div>

          <details className="card">
            <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
              How this differs from the {tool.short} workbook ({result.corrections.length} corrections)
            </summary>
            <p style={{ color: 'var(--muted)', margin: '10px 0' }}>
              The workbook&apos;s formulas are followed as written, except where they are plainly broken. Each
              departure is listed so a figure from this page can be reconciled with one from the workbook.
              Codes: {Object.entries(CODES).map(([c, d]) => (
                <span key={c} style={{ marginRight: 8 }}><span className={`badge ${CODE_BADGE[c]}`}>{c}</span> {d}</span>
              ))}
            </p>
            <ol style={{ margin: 0, paddingLeft: 20 }}>
              {result.corrections.map((c) => <li key={c} style={{ marginBottom: 6 }}>{c}</li>)}
            </ol>
          </details>
        </>
      )}

      {!result && !error && (
        <div className="card">
          <div className="empty" style={{ padding: '2rem 1rem' }}>
            <div className="empty-title">No line list loaded</div>
            <div className="empty-subtitle">
              Choose a tool above, then load its CSV. The cohort, the service coverage and a worklist of
              clients still owed a service appear here.
            </div>
          </div>
        </div>
      )}
    </>
  );
}
