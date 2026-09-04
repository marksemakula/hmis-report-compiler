'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  IconDraft, IconCloudUp, IconInbox, IconAlert, IconCheck,
  IconArrowRight, IconEye, IconUpload,
} from './icons';
import DistrictMap from './districtmap';
import MalariaChannel from './malariachannel';
import Mortality from './mortality';
import TbScreening from './tbscreening';
import useWidth from './usewidth';

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
const pct = (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(1)}%`);
const ordinal = (n) => {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
};

/** Anchor a tooltip to a column, flipping it inboard near either edge. */
function tipShift(percent) {
  return percent > 72 ? 'translateX(-100%)' : percent < 18 ? 'translateX(0)' : 'translateX(-50%)';
}

const TIP_STYLE = {
  position: 'absolute', top: 0, pointerEvents: 'none',
  background: '#fff', border: '1px solid rgba(4,32,69,.1)', borderRadius: 6,
  boxShadow: '0 16px 24px 2px rgba(0,0,0,.07)', padding: '.5rem .625rem',
  fontSize: '.75rem', whiteSpace: 'nowrap', zIndex: 2,
};

/* ------------------------------------------------------------ rate trend
 *
 * One continuous measure over time, so a line rather than columns. A single
 * series needs no legend - the card title names it - and only the last point
 * is directly labelled, per the "label selectively" rule.
 */
function RateTrend({ points }) {
  const [hover, setHover] = useState(null);
  const box = useRef(null);
  const W = useWidth(box);

  const H = 220;
  const padL = 38, padR = 44, padT = 14, padB = 28;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  if (points.length < 2) {
    return (
      <div className="empty">
        <div className="empty-title">Not enough history yet</div>
        <div className="empty-subtitle">
          A trend needs at least two aggregated periods. Analytics may not have run for
          the earlier months in this range.
        </div>
      </div>
    );
  }

  const band = plotW / (points.length - 1);
  const xOf = (i) => padL + band * i;
  const yOf = (v) => padT + plotH - (Math.max(0, Math.min(100, v)) / 100) * plotH;
  const ticks = [0, 25, 50, 75, 100];
  const last = points[points.length - 1];
  const active = hover === null ? null : points[hover];

  return (
    <div ref={box} style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}
        style={{ width: '100%', height: `${H}px`, display: 'block' }} role="img"
        aria-label="Average reporting rate by month">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={padL} x2={W - padR} y1={yOf(v)} y2={yOf(v)} stroke="#e5e7eb" strokeWidth="1" />
            <text x={padL - 8} y={yOf(v) + 4} textAnchor="end" fontSize="11" fill="#181818">{v}%</text>
          </g>
        ))}

        <path
          d={points.map((p, i) => `${i ? 'L' : 'M'}${xOf(i)},${yOf(p.rate)}`).join('')}
          fill="none" stroke="#066fd1" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        />

        {points.map((p, i) => (
          <g key={p.period}>
            {/* A 2px surface ring keeps the marker legible where it sits on
                the line, and widens the hit target at the same time. */}
            <circle cx={xOf(i)} cy={yOf(p.rate)} r={hover === i ? 5 : 4}
              fill="#066fd1" stroke="#fff" strokeWidth="2" />
            {/* Label every other month counting back from the newest, so the
                run ends on the current period instead of leaving two labels
                adjacent at the right edge. */}
            {(points.length <= 6 || (points.length - 1 - i) % 2 === 0) && (
              <text x={xOf(i)} y={H - 10} textAnchor="middle" fontSize="11" fill="#181818">
                {p.label.slice(0, 3)}
              </text>
            )}
            <rect x={xOf(i) - band / 2} y={padT} width={band} height={plotH} fill="transparent"
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
          </g>
        ))}

        <text x={xOf(points.length - 1) + 10} y={yOf(last.rate) + 4}
          fontSize="12" fontWeight="600" fill="#1f2937">{last.rate}%</text>
      </svg>

      {active && (() => {
        const p = (xOf(hover) / W) * 100;
        return (
          <div style={{ ...TIP_STYLE, left: `${p}%`, transform: tipShift(p) }}>
            <div className="fw-bold">{active.label}</div>
            <div className="text-secondary">Reporting rate {active.rate}%</div>
          </div>
        );
      })()}
    </div>
  );
}

/* --------------------------------------------------------------- pieces */

function StatTile({ Icon, tone, label, value, foot, valueTone }) {
  return (
    <div className="card">
      <div className="stat">
        <span className={`avatar soft-${tone}`}><Icon size={20} /></span>
        <div className="stat-body">
          <div className="page-pretitle">{label}</div>
          <div className={`stat-value${valueTone ? ` is-${valueTone}` : ''}`}>{value}</div>
          {foot && <div className="stat-foot">{foot}</div>}
        </div>
      </div>
    </div>
  );
}

/**
 * What is wrong with the plumbing, in words, or nothing at all.
 *
 * The standing System health panel is gone - the map has its place. But the
 * facts it carried are the ones that explain a submission which returns
 * SUCCESS and writes nothing, and dropping them outright would leave a Data
 * Officer with a silent failure and nowhere to look. So they are raised only
 * when one of them is actually wrong: invisible on a healthy morning, and in
 * front of you on the morning it matters.
 */
function healthWarnings(meta, agents) {
  const out = [];
  if (meta && !meta.dhis2_configured) out.push('DHIS2 credentials are not configured');
  if (meta && !meta.db_configured) out.push('the database is not configured');
  if (meta && !meta.orgUnit?.id) out.push('the facility organisation unit is not resolved');
  if (agents && !agents.online) {
    const seen = agents.agents?.[0];
    out.push(seen
      ? `the extraction agent was last seen ${Math.round(seen.seconds_ago / 60)} min ago`
      : 'no extraction agent has ever reported in');
  }
  return out;
}

const STATE = {
  PUSHED: { badge: 'ok', bar: 'bg-success', word: 'Submitted' },
  DRAFT:  { badge: 'warn', bar: 'bg-warning', word: 'Awaiting submission' },
  FAILED: { badge: 'bad', bar: 'bg-danger', word: 'Failed' },
};

/* ------------------------------------------------------------ facility tab */

function FacilityView({ loading, rows, types, meta, agents, user }) {
  const submitted = rows.filter((r) => r.push_status === 'PUSHED');
  const drafts = rows.filter((r) => r.push_status === 'DRAFT');
  const failed = rows.filter((r) => r.push_status === 'FAILED');
  const valuesSent = submitted.reduce((a, r) => a + (r.value_count || 0), 0);
  // Reports are returned newest first, so the last draft in the list is the
  // one that has been waiting longest.
  const oldestDraft = drafts.length ? drafts[drafts.length - 1] : null;

  const latestByType = new Map();
  for (const r of rows) if (!latestByType.has(r.type)) latestByType.set(r.type, r);
  const warnings = healthWarnings(meta, agents);

  return (
    <>
      {warnings.length > 0 && (
        <div className="alert warn">
          <strong>Check before submitting:</strong> {warnings.join('; ')}. These are the
          commonest reasons a submission reports success yet writes nothing.
          {user?.role === 'admin' && <> Metadata can be refreshed from <Link href="/admin">Administration</Link>.</>}
        </div>
      )}

      {/* Mortality takes the place the "Submitted to DHIS2" counter held. It is
          given two columns rather than one: ten bars labelled with ICD-11 terms
          need the width, and a submission counter is a number about this app
          while this is a number about the hospital. The submitted total has not
          been dropped - it reads on the Reports page, where the submissions
          themselves are. */}
      {/* Three columns rather than four. The two submission counters are a line
          of text each and do not need a column apiece; sharing one leaves the
          TB screening chart the width to put its legend beside the donut
          instead of under it, which is most of the difference between a card
          the height of this row and a card twice it. */}
      <div className="row-cards own-height" style={{ marginBottom: 'var(--tblr-page-padding)',
        gridTemplateColumns: 'minmax(0,1.7fr) minmax(0,1fr) minmax(0,1.5fr)' }}>
        {/* TB screening takes the place the "Reports compiled" counter held.
            A count of what this app compiled is a number about the app; the
            share of attendances screened is a number about the hospital, and
            the compiled total still reads on the Reports page. */}
        <div className="card flush">
          <div className="card-body">
            {/* The period is the card's own, and it is no longer always this
                year, so the heading no longer claims it is. Which weeks of
                which year the figures cover reads under the chart, from the
                response rather than from a title written once. */}
            <div className="page-pretitle">TB screening of attendances</div>
            <TbScreening />
          </div>
        </div>
        <div className="card-stack">
          <StatTile Icon={IconInbox} tone="warning" label="Awaiting submission"
            value={loading ? '—' : nf(drafts.length)}
            foot={loading ? ' ' : oldestDraft ? `Oldest: ${formatPeriod(oldestDraft.period)}` : 'Nothing waiting'} />
          <StatTile Icon={IconAlert} tone="danger" label="Failed submissions"
            valueTone={failed.length ? 'danger' : undefined}
            value={loading ? '' : nf(failed.length)}
            foot={loading ? ' ' : failed.length ? `Most recent: ${formatPeriod(failed[0].period)}` : 'None recorded'} />
        </div>
        <Mortality />
      </div>

      {/* alignItems start, not the grid default: the map card is roughly twice
          the height of the chart card, and stretching the chart to match it
          leaves four hundred pixels of empty card under the axis. */}
      <div className="grid cols-2"
        style={{ gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)', alignItems: 'start' }}>
        <div className="card flush">
          <div className="card-header">
            <div>
              <h2 className="card-title">Malaria channel</h2>
              <div className="card-subtitle">
                Cases by ISO week, against percentile bands from previous years
              </div>
            </div>
            <div className="card-actions">
              <Link href="/reports" className="btn secondary sm">All reports<IconArrowRight size={14} /></Link>
            </div>
          </div>
          <div className="card-body"><MalariaChannel scope="facility" /></div>
        </div>

        <div className="card flush">
          <div className="card-header">
            <div>
              <h2 className="card-title">Busoga districts</h2>
              <div className="card-subtitle">This hospital&rsquo;s district is outlined</div>
            </div>
          </div>
          <div className="card-body"><DistrictMap /></div>
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
                        <span className="text-secondary">{loading ? ' ' : 'Nothing compiled yet'}</span>
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

/* ------------------------------------------------- region / national tab */

const TILE_ICONS = [IconDraft, IconCloudUp, IconCheck, IconInbox];
const TILE_TONES = ['primary', 'success', 'azure', 'warning'];

/** Reporting rate bands. The percentage is always written beside the bar, so
 *  the colour supplements the number rather than carrying it alone. */
function rateTone(rate) {
  if (rate === null || rate === undefined) return 'muted';
  if (rate >= 90) return 'success';
  if (rate >= 70) return 'warning';
  return 'danger';
}

function ScopeView({ data, error, loading, onRetry }) {
  if (loading) {
    return (
      <>
        <div className="loading-bar" style={{ marginBottom: 'var(--tblr-page-padding)' }} />
        <div className="card">
          <div className="text-secondary">
            Reading DHIS2 analytics… this asks the national instance about every facility
            in scope and can take a few seconds.
          </div>
        </div>
      </>
    );
  }

  if (error) {
    return (
      <div className="card flush">
        <span className="card-status-top bg-danger" />
        <div className="card-body">
          <div className="empty">
            <div className="empty-icon"><IconAlert size={40} /></div>
            <div className="empty-title">These figures could not be read</div>
            <div className="empty-subtitle" style={{ marginBottom: '1rem' }}>{error}</div>
            <button type="button" className="btn secondary" onClick={onRetry}>Try again</button>
          </div>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const rank = data.ranking;
  const inTop = rank?.top?.some((p) => p.id === data.facilityId);

  return (
    <>
      <div className="row-cards" style={{ marginBottom: 'var(--tblr-page-padding)' }}>
        {data.tiles.map((t, i) => {
          const Icon = TILE_ICONS[i % TILE_ICONS.length];
          return (
            <StatTile key={t.label} Icon={Icon} tone={t.tone || TILE_TONES[i % TILE_TONES.length]}
              label={t.label}
              value={t.value === null || t.value === undefined
                ? '—'
                : t.unit === '%' ? pct(t.value) : nf(t.value)}
              foot={t.foot} />
          );
        })}
      </div>

      {/* The map and the peer table share a row. Busoga is tall and narrow, so
          a full-width map card would leave most of its own width empty; giving
          half the row to the ranking uses the space that shape cannot. */}
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <div className="card flush">
          <div className="card-header">
            <div>
              <h2 className="card-title">{data.orgUnit.name} by district</h2>
              <div className="card-subtitle">
                Choose what to shade the districts by, and the period to read it for
              </div>
            </div>
          </div>
          <div className="card-body"><DistrictMap /></div>
        </div>

        <div className="card flush">
          <div className="card-header">
            <h2 className="card-title">Jinja RRH among its peers</h2>
          </div>
          <div className="card-body" style={{ paddingTop: '.75rem' }}>
            {!rank || rank.stale || !rank.rank ? (
              <div className="text-secondary" style={{ fontSize: '.8125rem' }}>
                No peer figures for {rank?.periodLabel || 'this period'}. Analytics may not have
                run for it yet, or the hospital filed no {rank?.dataSet || '105:01'} return.
              </div>
            ) : (
              <>
                <div className="stat-value" style={{ marginBottom: '.25rem' }}>
                  {ordinal(rank.rank)}
                  <small>of {nf(rank.of)} facilities</small>
                </div>
                <div className="stat-foot" style={{ marginBottom: '.875rem' }}>
                  By {rank.dataSet} reporting rate, {rank.periodLabel}
                </div>
                {rank.top.map((p) => (
                  <div key={p.id} className="d-flex items-center gap-2"
                    style={{ padding: '.3125rem 0', fontSize: '.8125rem' }}>
                    <span className="text-secondary" style={{ width: '1.5rem' }}>{p.rank}</span>
                    <span className={p.id === data.facilityId ? 'fw-bold' : ''}
                      style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {p.name}
                    </span>
                    <span className="ms-auto fw-medium">{pct(p.rate)}</span>
                  </div>
                ))}
                {!inTop && rank.facility && (
                  <div className="d-flex items-center gap-2"
                    style={{ padding: '.3125rem 0', fontSize: '.8125rem', borderTop: '1px solid rgba(4,32,69,.1)', marginTop: '.3125rem' }}>
                    <span className="text-secondary" style={{ width: '1.5rem' }}>{rank.facility.rank}</span>
                    <span className="fw-bold" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {rank.facility.name}
                    </span>
                    <span className="ms-auto fw-medium">{pct(rank.facility.rate)}</span>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      <div className="card flush" style={{ marginTop: 'var(--tblr-page-padding)' }}>
        <div className="card-header">
          <div>
            <h2 className="card-title">Reporting rate</h2>
            <div className="card-subtitle">
              Monthly data sets across {data.orgUnit.name}, averaged
            </div>
          </div>
        </div>
        <div className="card-body"><RateTrend points={data.trend || []} /></div>
      </div>

      {data.indicators?.some((i) => i.value !== null) && (
        <div className="card flush" style={{ marginTop: 'var(--tblr-page-padding)' }}>
          <div className="card-header">
            <div>
              <h2 className="card-title">Headline totals</h2>
              <div className="card-subtitle">
                {data.indicators[0]?.periodLabel} · {data.orgUnit.name}
              </div>
            </div>
          </div>
          <div className="card-body">
            <div className="datagrid">
              {data.indicators.map((ind) => (
                <div key={ind.label}>
                  <div className="datagrid-title">{ind.label}</div>
                  <div className="datagrid-content stat-value" style={{ fontSize: '1.25rem', lineHeight: '1.75rem' }}>
                    {ind.value === null ? '—' : nf(ind.value)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="page-header" style={{ marginTop: 'var(--tblr-page-padding-y)', marginBottom: '1rem' }}>
        <div>
          <div className="page-pretitle">Completeness by data set</div>
          <h2 className="page-title">Reports</h2>
        </div>
      </div>

      <div className="row-cards">
        {data.dataSets.map((d) => {
          const tone = rateTone(d.reportingRate);
          return (
            <div key={d.type} className="card flush">
              <span className={`card-status-top bg-${tone === 'muted' ? 'muted' : tone}`} />
              <div className="card-body">
                <div className="d-flex flex-wrap items-center gap-2" style={{ marginBottom: '.5rem' }}>
                  <span className="badge primary">{d.short}</span>
                  <span className="badge muted">{d.periodType}</span>
                </div>
                <div className="fw-medium" style={{ marginBottom: '.625rem' }}>{d.label}</div>
                {d.stale ? (
                  <div className="text-secondary" style={{ fontSize: '.8125rem' }}>
                    Not yet aggregated for {d.periodLabel}
                  </div>
                ) : (
                  <>
                    <div className="d-flex items-center gap-2" style={{ marginBottom: '.375rem' }}>
                      <span className="stat-value" style={{ fontSize: '1.125rem', lineHeight: '1.5rem' }}>
                        {pct(d.reportingRate)}
                      </span>
                      <span className="text-secondary ms-auto" style={{ fontSize: '.75rem' }}>
                        {nf(d.actual)} of {nf(d.expected)}
                      </span>
                    </div>
                    <div className="progress">
                      <span className={`progress-bar ${tone}`}
                        style={{ width: `${Math.max(0, Math.min(100, d.reportingRate || 0))}%` }} />
                    </div>
                    <div className="text-secondary" style={{ fontSize: '.75rem', marginTop: '.375rem' }}>
                      {d.onTime !== null ? `${nf(d.onTime)} on time` : 'On-time figure unavailable'} · {d.periodLabel}
                    </div>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ page */

const FALLBACK_SCOPES = [
  { scope: 'facility', short: 'Jinja RRH', name: 'Jinja Regional Referral Hospital', source: 'local' },
  { scope: 'region', short: 'Busoga Region', name: 'Busoga Region', source: 'dhis2' },
  { scope: 'national', short: 'MoH - National', name: 'Ministry of Health - National', source: 'dhis2' },
];

export default function Dashboard() {
  const router = useRouter();
  const [tab, setTab] = useState('facility');
  const [user, setUser] = useState(null);
  const [reports, setReports] = useState(null);
  const [types, setTypes] = useState(null);
  const [meta, setMeta] = useState(null);
  const [agents, setAgents] = useState(null);
  const [scopes, setScopes] = useState(null);
  const [error, setError] = useState('');
  // Each wider scope is fetched once, on first view, and kept. Analytics is
  // slow enough that re-querying on every tab switch would be felt.
  const [wide, setWide] = useState({});

  const get = useCallback(async (url) => {
    const r = await fetch(url);
    if (r.status === 401) { router.push('/login'); return null; }
    if (!r.ok) return null;
    return r.json().catch(() => null);
  }, [router]);

  useEffect(() => {
    let live = true;

    /* One panel failing must not blank the page. A dashboard whose job is to
       say what is wrong is the last thing that should go white when something
       is: if the agent table is unreachable, the report figures are still
       worth showing, and the health strip says the agent is unknown rather
       than claiming it is offline. */
    (async () => {
      const me = await get('/api/py/auth/me');
      if (!live) return;
      if (!me) { setError('Could not confirm your session.'); return; }
      setUser(me);

      const [rep, typ, mt, ag, sc] = await Promise.all([
        get('/api/py/reports'),
        get('/api/py/report-types'),
        get('/api/py/meta'),
        get('/api/py/agents'),
        get('/api/py/scopes'),
      ]);
      if (!live) return;
      setReports(rep?.reports || []);
      setTypes(typ?.reportTypes || []);
      setMeta(mt || null);
      setAgents(ag || null);
      // The tab strip is drawn even if the hierarchy lookup failed - the two
      // wider tabs then report their own error when opened, which says more
      // than silently hiding them would.
      setScopes(sc?.scopes || FALLBACK_SCOPES);
      if (!rep) setError('The compiled report list could not be loaded.');
    })();

    return () => { live = false; };
  }, [get]);

  const loadScope = useCallback(async (scope) => {
    setWide((w) => ({ ...w, [scope]: { loading: true } }));
    const r = await fetch(`/api/py/overview?scope=${encodeURIComponent(scope)}`);
    if (r.status === 401) { router.push('/login'); return; }
    const body = await r.json().catch(() => null);
    if (!r.ok) {
      setWide((w) => ({
        ...w,
        [scope]: {
          loading: false,
          error: body?.detail || `DHIS2 did not answer (HTTP ${r.status}).`,
        },
      }));
      return;
    }
    setWide((w) => ({
      ...w,
      [scope]: { loading: false, data: { ...body, facilityId: meta?.orgUnit?.id } },
    }));
  }, [router, meta]);

  useEffect(() => {
    if (tab === 'facility') return;
    if (wide[tab] && !wide[tab].error) return;
    if (wide[tab]?.loading) return;
    loadScope(tab);
    // Deliberately keyed on the tab alone: re-running when `wide` changes
    // would refetch the moment the result lands.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const loading = reports === null;
  const rows = reports || [];
  const isOfficer = user && user.role !== 'viewer';
  const tabs = scopes || FALLBACK_SCOPES;
  const current = tabs.find((t) => t.scope === tab);
  const state = wide[tab] || {};

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-pretitle">
            {tab === 'facility'
              ? (meta?.orgUnit?.name || 'Jinja Regional Referral Hospital')
              : (state.data?.orgUnit?.name || current?.name || '')}
          </div>
          <h1 className="page-title">Dashboard</h1>
        </div>
        <div className="page-header-actions">
          <Link href="/preview" className="btn secondary"><IconEye size={16} />Preview a form</Link>
          {isOfficer && <Link href="/compile" className="btn"><IconUpload size={16} />Compile a report</Link>}
        </div>
      </div>

      <nav className="nav-tabs" aria-label="Dashboard scope">
        {tabs.map((t) => (
          <button
            key={t.scope}
            type="button"
            className={`nav-tab ${tab === t.scope ? 'active' : ''}`}
            aria-current={tab === t.scope ? 'true' : undefined}
            onClick={() => setTab(t.scope)}
          >
            {t.short}
          </button>
        ))}
      </nav>

      {error && tab === 'facility' && <div className="alert error">{error}</div>}

      {/* The facility tab counts our own compilation workflow; the wider two
          count whether each facility's report arrived at all. Saying so once,
          on the tabs where it applies, stops the two being read as one
          measure that mysteriously changes scale. */}
      {tab !== 'facility' && !state.loading && !state.error && state.data && (
        <div className="alert info">
          These are DHIS2 figures for {state.data.orgUnit.name} — how many facilities filed each
          return, not what this hospital compiled. The Jinja RRH tab is the compilation workflow.
        </div>
      )}

      {tab === 'facility'
        ? <FacilityView loading={loading} rows={rows} types={types} meta={meta} agents={agents} user={user} />
        : <ScopeView data={state.data} error={state.error} loading={!!state.loading}
            onRetry={() => loadScope(tab)} />}
    </>
  );
}
