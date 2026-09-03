'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
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
const pct = (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(1)}%`);
const ordinal = (n) => {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
};

/* ------------------------------------------------------ compilation chart
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

/** Anchor a tooltip to a column, flipping it inboard near either edge. */
function tipShift(percent) {
  return percent > 72 ? 'translateX(-100%)' : percent < 18 ? 'translateX(0)' : 'translateX(-50%)';
}

/**
 * The rendered pixel width of an element, for use as an SVG's viewBox width.
 *
 * A fixed viewBox scaled to fit its container scales *everything* with it,
 * type and stroke weights included. That was tolerable while the page was
 * capped at 1320px; on a full-width layout the same chart stretches to twice
 * the width and the axis labels arrive at 24px. Matching the viewBox to the
 * measured width instead makes one user unit one CSS pixel, so an 11px label
 * is 11px and a 24px bar is 24px on a laptop and on a wall display alike.
 *
 * The fallback matters: ResizeObserver has not fired on the first paint, and
 * does not exist at all during the server render.
 */
function useWidth(ref, fallback = 760) {
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(([entry]) => {
      const next = Math.round(entry.contentRect.width);
      if (next > 0) setWidth(next);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}

const TIP_STYLE = {
  position: 'absolute', top: 0, pointerEvents: 'none',
  background: '#fff', border: '1px solid rgba(4,32,69,.1)', borderRadius: 6,
  boxShadow: '0 16px 24px 2px rgba(0,0,0,.07)', padding: '.5rem .625rem',
  fontSize: '.75rem', whiteSpace: 'nowrap', zIndex: 2,
};

function ActivityChart({ buckets }) {
  const [hover, setHover] = useState(null);
  const box = useRef(null);
  const W = useWidth(box);

  const H = 240;
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
    <div ref={box} style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}
        style={{ width: '100%', height: `${H}px`, display: 'block' }} role="img"
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
        const p = ((band * hover + band / 2 + padL) / W) * 100;
        return (
          <div style={{ ...TIP_STYLE, left: `${p}%`, transform: tipShift(p) }}>
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
            <text x={padL - 8} y={yOf(v) + 4} textAnchor="end" fontSize="11" fill="#6b7280">{v}%</text>
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
              <text x={xOf(i)} y={H - 10} textAnchor="middle" fontSize="11" fill="#6b7280">
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

/* ------------------------------------------------------------ facility tab */

function FacilityView({ loading, rows, types, meta, agents, user }) {
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

  const latestByType = new Map();
  for (const r of rows) if (!latestByType.has(r.type)) latestByType.set(r.type, r);
  const agentSeen = agents?.agents?.[0];

  return (
    <>
      <div className="row-cards" style={{ marginBottom: 'var(--tblr-page-padding)' }}>
        <StatTile Icon={IconDraft} tone="primary" label="Reports compiled"
          value={loading ? '—' : nf(rows.length)}
          foot={loading ? ' ' : `${nf(compiledThisYear)} in the last 12 months`} />
        <StatTile Icon={IconCloudUp} tone="success" label="Submitted to DHIS2"
          value={loading ? '—' : nf(submitted.length)}
          foot={loading ? ' ' : `${nf(valuesSent)} data values accepted`} />
        <StatTile Icon={IconInbox} tone="warning" label="Awaiting submission"
          value={loading ? '—' : nf(drafts.length)}
          foot={loading ? ' ' : oldestDraft ? `Oldest: ${formatPeriod(oldestDraft.period)}` : 'Nothing waiting'} />
        <StatTile Icon={IconAlert} tone="danger" label="Failed submissions"
          value={loading ? '—' : nf(failed.length)}
          foot={loading ? ' ' : failed.length ? `Most recent: ${formatPeriod(failed[0].period)}` : 'None recorded'} />
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
          <div className="card-header"><h2 className="card-title">System health</h2></div>
          <div className="card-body" style={{ paddingTop: 0 }}>
            <HealthRow Icon={IconCloudUp} ok={meta ? !!meta.dhis2_configured : null}
              label="DHIS2 credentials"
              detail={meta?.instance ? String(meta.instance).replace(/^https?:\/\//, '') : 'National instance'} />
            <HealthRow Icon={IconDatabase} ok={meta ? !!meta.db_configured : null}
              label="Database" detail="Staging data, compiled reports and the audit trail" />
            <HealthRow Icon={IconPlug} ok={agents ? !!agents.online : null}
              label="Extraction agent"
              detail={!agents ? 'Status unavailable'
                : agents.online ? `${agentSeen?.host || 'Agent'} reporting in`
                  : agentSeen ? `Last seen ${Math.round(agentSeen.seconds_ago / 60)} min ago`
                    : 'No agent has ever reported in'} />
            <HealthRow Icon={IconCheck} ok={meta ? !!meta.orgUnit?.id : null}
              label="Facility"
              detail={meta?.orgUnit?.name ? `${meta.orgUnit.name} · ${meta.orgUnit.id}` : 'Organisation unit not resolved'} />
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

      <div className="grid cols-2" style={{ gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)' }}>
        <div className="card flush">
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
