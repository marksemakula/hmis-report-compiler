'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  IconDraft, IconCloudUp, IconInbox, IconAlert, IconCheck,
  IconDatabase, IconPlug, IconArrowRight, IconEye, IconUpload,
} from './icons';

/* ---------------------------------------------------------------- periods */

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];

/**
 * A period identifier as a person would say it. Three cadences share this
 * column - `202607`, `2026W35`, `2026Q2` - and printed raw they are easy to
 * misread as one another, which is exactly the mistake that puts a week's
 * tally against a month.
 */
function formatPeriod(p) {
  const s = String(p || '');
  let m = /^(\d{4})W(\d{1,2})$/i.exec(s);
  if (m) return `Week ${Number(m[2])}, ${m[1]}`;
  m = /^(\d{4})Q([1-4])$/i.exec(s);
  if (m) return `Q${m[2]} ${m[1]}`;
  m = /^(\d{4})(\d{2})$/.exec(s);
  if (m && +m[2] >= 1 && +m[2] <= 12) return `${MONTHS[+m[2] - 1]} ${m[1]}`;
  return s || '—';
}

const nf = (n) => Number(n || 0).toLocaleString('en-GB');

/* ------------------------------------------------------------------ chart
 *
 * Reports compiled per month, split by what became of them. Three states, so
 * a legend is always drawn and the colours are never the only channel.
 *
 * The obvious palette - green for submitted, red for failed - is the one
 * thing this chart must not do: green #2fb344 against red #d63939 separates
 * by only 7.8 in deuteranopia, below the 8 floor, and "did it reach DHIS2"
 * is the whole question the chart answers. Tabler's primary blue against the
 * same red separates by 23.4, and against the neutral grey by 16.4. Green is
 * still used for *status*, where a word sits beside it; it is not used to
 * carry meaning on its own in a chart.
 */
const SERIES = [
  { key: 'PUSHED', label: 'Submitted', color: '#066fd1' },
  { key: 'DRAFT',  label: 'Awaiting submission', color: '#9ca3af' },
  { key: 'FAILED', label: 'Failed', color: '#d63939' },
];

/** Rounded at the data end, square at the baseline, per the mark spec. */
function barPath(x, y, w, h, roundTop) {
  const r = roundTop ? Math.min(4, w / 2, h) : 0;
  if (!r) return `M${x},${y}h${w}v${h}h${-w}z`;
  return `M${x},${y + r}a${r},${r} 0 0 1 ${r},${-r}h${w - 2 * r}a${r},${r} 0 0 1 ${r},${r}v${h - r}h${-w}z`;
}

function ActivityChart({ buckets }) {
  const [hover, setHover] = useState(null);

  const W = 760, H = 240;
  const padL = 34, padR = 8, padT = 12, padB = 28;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const band = plotW / Math.max(buckets.length, 1);
  const barW = Math.min(24, band - 12);

  const peak = Math.max(1, ...buckets.map((b) => b.total));
  // Clean ticks: a small integer count wants 1s, not 0.7s.
  const step = peak <= 4 ? 1 : peak <= 8 ? 2 : Math.ceil(peak / 4);
  const top = Math.ceil(peak / step) * step;
  const ticks = [];
  for (let v = 0; v <= top; v += step) ticks.push(v);

  const yOf = (v) => padT + plotH - (v / top) * plotH;
  const active = hover === null ? null : buckets[hover];

  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} role="img"
        aria-label="Reports compiled each month, split by submission outcome">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={padL} x2={W - padR} y1={yOf(v)} y2={yOf(v)} stroke="#e5e7eb" strokeWidth="1" />
            <text x={padL - 8} y={yOf(v) + 4} textAnchor="end" fontSize="11" fill="#6b7280">{v}</text>
          </g>
        ))}

        {buckets.map((b, i) => {
          const cx = padL + band * i + band / 2;
          let cursor = padT + plotH;
          const stack = SERIES.map((s) => ({ ...s, n: b[s.key] || 0 })).filter((s) => s.n > 0);
          return (
            <g key={b.key} opacity={hover === null || hover === i ? 1 : 0.5}>
              {stack.map((s, j) => {
                const h = (s.n / top) * plotH;
                // 2px of surface between touching segments does the separating.
                const gap = j < stack.length - 1 ? 2 : 0;
                const drawn = Math.max(1, h - gap);
                cursor -= h;
                return (
                  <path key={s.key} d={barPath(cx - barW / 2, cursor + gap, barW, drawn, j === stack.length - 1)}
                    fill={s.color} />
                );
              })}
              <text x={cx} y={H - 10} textAnchor="middle" fontSize="11" fill="#6b7280">{b.short}</text>
              <rect x={padL + band * i} y={padT} width={band} height={plotH} fill="transparent"
                onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
            </g>
          );
        })}
        <line x1={padL} x2={W - padR} y1={padT + plotH} y2={padT + plotH} stroke="#d1d5db" strokeWidth="1" />
      </svg>

      {active && (() => {
        /* Anchor the tooltip to the hovered column, but flip it inboard near
           either edge so it never hangs off the card. Without this the last
           two months put it outside the card entirely. */
        const pct = ((band * hover + band / 2 + padL) / W) * 100;
        const shift = pct > 72 ? 'translateX(-100%)' : pct < 18 ? 'translateX(0)' : 'translateX(-50%)';
        return (
        <div style={{
          position: 'absolute', top: 0,
          left: `${pct}%`,
          transform: shift, pointerEvents: 'none',
          background: '#fff', border: '1px solid rgba(4,32,69,.1)', borderRadius: 6,
          boxShadow: '0 16px 24px 2px rgba(0,0,0,.07)', padding: '.5rem .625rem',
          fontSize: '.75rem', whiteSpace: 'nowrap', zIndex: 2,
        }}>
          <div className="fw-bold" style={{ marginBottom: '.25rem' }}>{active.label}</div>
          {active.total === 0 ? <div className="text-secondary">Nothing compiled</div> : SERIES.map((s) => (
            active[s.key] > 0 && (
              <div key={s.key} className="d-flex items-center gap-2">
                <span style={{ width: 8, height: 8, borderRadius: 2, background: s.color, flex: 'none' }} />
                <span className="text-secondary">{s.label}</span>
                <span className="ms-auto fw-medium" style={{ paddingLeft: '.75rem' }}>{active[s.key]}</span>
              </div>
            )
          ))}
        </div>
        );
      })()}

      <div className="d-flex gap-4 items-center flex-wrap" style={{ marginTop: '.75rem' }}>
        {SERIES.map((s) => (
          <span key={s.key} className="d-flex items-center gap-2" style={{ fontSize: '.75rem' }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: s.color, flex: 'none' }} />
            <span className="text-secondary">{s.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- the page */

function StatTile({ Icon, tone, label, value, foot }) {
  return (
    <div className="card">
      <div className="stat">
        <span className={`avatar soft-${tone}`}><Icon size={20} /></span>
        <div className="stat-body">
          <div className="page-pretitle">{label}</div>
          <div className="stat-value">{value}</div>
          {foot && <div className="stat-foot">{foot}</div>}
        </div>
      </div>
    </div>
  );
}

function HealthRow({ ok, label, detail, Icon }) {
  return (
    <div className="d-flex items-center gap-3" style={{ padding: '.625rem 0', borderTop: '1px solid rgba(4,32,69,.1)' }}>
      <span className={`avatar sm soft-${ok === null ? 'primary' : ok ? 'success' : 'danger'}`}><Icon size={16} /></span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="fw-medium">{label}</div>
        <div className="text-secondary" style={{ fontSize: '.75rem' }}>{detail}</div>
      </div>
      <span className={`badge ${ok === null ? 'muted' : ok ? 'ok' : 'bad'}`}>
        {ok === null ? 'Unknown' : ok ? 'Ready' : 'Attention'}
      </span>
    </div>
  );
}

const STATE = {
  PUSHED: { badge: 'ok', bar: 'bg-success', word: 'Submitted' },
  DRAFT:  { badge: 'warn', bar: 'bg-warning', word: 'Awaiting submission' },
  FAILED: { badge: 'bad', bar: 'bg-danger', word: 'Failed' },
};

export default function Dashboard() {
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [reports, setReports] = useState(null);
  const [types, setTypes] = useState(null);
  const [meta, setMeta] = useState(null);
  const [agents, setAgents] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;

    /* One panel failing must not blank the page. A dashboard whose job is to
       say what is wrong is the last thing that should go white when something
       is: if the agent table is unreachable, the report figures are still
       worth showing, and the health strip says the agent is unknown rather
       than claiming it is offline. */
    const get = async (url) => {
      const r = await fetch(url);
      if (r.status === 401) { router.push('/login'); return null; }
      if (!r.ok) return null;
      return r.json().catch(() => null);
    };

    (async () => {
      const me = await get('/api/py/auth/me');
      if (!live) return;
      if (!me) { setError('Could not confirm your session.'); return; }
      setUser(me);

      const [rep, typ, mt, ag] = await Promise.all([
        get('/api/py/reports'),
        get('/api/py/report-types'),
        get('/api/py/meta'),
        get('/api/py/agents'),
      ]);
      if (!live) return;
      setReports(rep?.reports || []);
      setTypes(typ?.reportTypes || []);
      setMeta(mt || null);
      setAgents(ag || null);
      if (!rep) setError('The compiled report list could not be loaded.');
    })();

    return () => { live = false; };
  }, [router]);

  const loading = reports === null;
  const rows = reports || [];
  const isOfficer = user && user.role !== 'viewer';

  const submitted = rows.filter((r) => r.push_status === 'PUSHED');
  const drafts = rows.filter((r) => r.push_status === 'DRAFT');
  const failed = rows.filter((r) => r.push_status === 'FAILED');
  const valuesSent = submitted.reduce((a, r) => a + (r.value_count || 0), 0);
  // Reports are returned newest first, so the last draft in the list is the
  // one that has been waiting longest.
  const oldestDraft = drafts.length ? drafts[drafts.length - 1] : null;

  /* Twelve months back from this one, by the date the report was compiled.
     Bucketing on generated_at rather than the reporting period is what lets
     monthly, weekly and quarterly reports share one axis honestly. */
  const buckets = (() => {
    const now = new Date();
    const out = [];
    for (let i = 11; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      out.push({
        key: `${d.getFullYear()}-${d.getMonth()}`,
        short: MONTHS[d.getMonth()].slice(0, 3),
        label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}`,
        PUSHED: 0, DRAFT: 0, FAILED: 0, total: 0,
      });
    }
    const index = new Map(out.map((b) => [b.key, b]));
    for (const r of rows) {
      const d = new Date(r.generated_at);
      if (Number.isNaN(d.getTime())) continue;
      const b = index.get(`${d.getFullYear()}-${d.getMonth()}`);
      if (!b) continue;
      if (b[r.push_status] === undefined) continue;
      b[r.push_status] += 1;
      b.total += 1;
    }
    return out;
  })();
  const compiledThisYear = buckets.reduce((a, b) => a + b.total, 0);

  /* The newest compiled report for each registered data set. */
  const latestByType = new Map();
  for (const r of rows) if (!latestByType.has(r.type)) latestByType.set(r.type, r);

  const agentSeen = agents?.agents?.[0];

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-pretitle">
            {meta?.orgUnit?.name || 'Jinja Regional Referral Hospital'}
          </div>
          <h1 className="page-title">Dashboard</h1>
        </div>
        <div className="page-header-actions">
          <Link href="/preview" className="btn secondary"><IconEye size={16} />Preview a form</Link>
          {isOfficer && <Link href="/compile" className="btn"><IconUpload size={16} />Compile a report</Link>}
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="row-cards" style={{ marginBottom: 'var(--tblr-page-padding)' }}>
        <StatTile
          Icon={IconDraft} tone="primary" label="Reports compiled"
          value={loading ? '—' : nf(rows.length)}
          foot={loading ? ' ' : `${nf(compiledThisYear)} in the last 12 months`}
        />
        <StatTile
          Icon={IconCloudUp} tone="success" label="Submitted to DHIS2"
          value={loading ? '—' : nf(submitted.length)}
          foot={loading ? ' ' : `${nf(valuesSent)} data values accepted`}
        />
        <StatTile
          Icon={IconInbox} tone="warning" label="Awaiting submission"
          value={loading ? '—' : nf(drafts.length)}
          foot={loading ? ' '
            : oldestDraft ? `Oldest: ${formatPeriod(oldestDraft.period)}` : 'Nothing waiting'}
        />
        <StatTile
          Icon={IconAlert} tone="danger" label="Failed submissions"
          value={loading ? '—' : nf(failed.length)}
          foot={loading ? ' '
            : failed.length ? `Most recent: ${formatPeriod(failed[0].period)}` : 'None recorded'}
        />
      </div>

      <div className="grid cols-2" style={{ gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)' }}>
        <div className="card flush">
          <div className="card-header">
            <div>
              <h2 className="card-title">Compilation activity</h2>
              <div className="card-subtitle">Reports compiled each month, by submission outcome</div>
            </div>
            <div className="card-actions">
              <Link href="/reports" className="btn secondary sm">All reports<IconArrowRight size={14} /></Link>
            </div>
          </div>
          <div className="card-body">
            {loading ? <div className="text-secondary">Loading…</div>
              : rows.length === 0 ? (
                <div className="empty">
                  <div className="empty-icon"><IconDraft size={40} /></div>
                  <div className="empty-title">Nothing has been compiled yet</div>
                  <div className="empty-subtitle">
                    Once a register extract or weekly tally has been compiled, the month-by-month
                    record of what was submitted appears here.
                  </div>
                </div>
              ) : <ActivityChart buckets={buckets} />}
          </div>
        </div>

        <div className="card flush">
          <div className="card-header">
            <h2 className="card-title">System health</h2>
          </div>
          <div className="card-body" style={{ paddingTop: 0 }}>
            <HealthRow
              Icon={IconCloudUp}
              ok={meta ? !!meta.dhis2_configured : null}
              label="DHIS2 credentials"
              detail={meta?.instance
                ? String(meta.instance).replace(/^https?:\/\//, '')
                : 'National instance'}
            />
            <HealthRow
              Icon={IconDatabase}
              ok={meta ? !!meta.db_configured : null}
              label="Database"
              detail="Staging data, compiled reports and the audit trail"
            />
            <HealthRow
              Icon={IconPlug}
              ok={agents ? !!agents.online : null}
              label="Extraction agent"
              detail={!agents ? 'Status unavailable'
                : agents.online ? `${agentSeen?.host || 'Agent'} reporting in`
                  : agentSeen ? `Last seen ${Math.round(agentSeen.seconds_ago / 60)} min ago`
                    : 'No agent has ever reported in'}
            />
            <HealthRow
              Icon={IconCheck}
              ok={meta ? !!meta.orgUnit?.id : null}
              label="Facility"
              detail={meta?.orgUnit?.name
                ? `${meta.orgUnit.name} · ${meta.orgUnit.id}`
                : 'Organisation unit not resolved'}
            />
            <p className="text-secondary" style={{ fontSize: '.75rem', marginTop: '.75rem', marginBottom: 0 }}>
              These four explain most submissions that return success yet write nothing.
              {user?.role === 'admin' && <> Metadata can be refreshed from <Link href="/admin">Administration</Link>.</>}
            </p>
          </div>
        </div>
      </div>

      <div className="page-header" style={{ marginTop: 'var(--tblr-page-padding-y)', marginBottom: '1rem' }}>
        <div>
          <div className="page-pretitle">Registered data sets</div>
          <h2 className="page-title">Reports</h2>
        </div>
      </div>

      {!types || types.length === 0 ? (
        <div className="card">
          <div className="text-secondary">
            {loading ? 'Loading…' : 'The registered report list could not be loaded.'}
          </div>
        </div>
      ) : (
        <div className="row-cards">
          {types.map((t) => {
            const latest = latestByType.get(t.type);
            const state = latest ? STATE[latest.push_status] : null;
            return (
              <Link key={t.type} href={`/preview?report=${t.type}`} className="card-link">
                <div className="card flush">
                  <span className={`card-status-top ${state ? state.bar : 'bg-muted'}`} />
                  <div className="card-body">
                    <div className="d-flex flex-wrap items-center gap-2" style={{ marginBottom: '.5rem' }}>
                      <span className="badge primary">{t.short}</span>
                      <span className="badge muted">{t.periodType}</span>
                      {!t.compiler && <span className="badge muted" title="Registered and previewable; no compiler yet">Preview only</span>}
                    </div>
                    <div className="fw-medium" style={{ marginBottom: '.5rem' }}>{t.label}</div>
                    <div className="d-flex items-center gap-2" style={{ fontSize: '.8125rem' }}>
                      {latest ? (
                        <>
                          <span className="text-secondary">{formatPeriod(latest.period)}</span>
                          <span className={`badge ${state.badge} ms-auto`}>{state.word}</span>
                        </>
                      ) : (
                        <span className="text-secondary">
                          {loading ? ' ' : 'Nothing compiled yet'}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </>
  );
}
