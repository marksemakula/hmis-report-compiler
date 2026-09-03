'use client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import useWidth from './usewidth';

/* District choropleth for the region.
 *
 * The outlines are DHIS2's own organisation unit geometry, fetched once and
 * kept; the values change with every turn of a filter and are fetched on their
 * own. No mapping library: Leaflet and Mapbox both want a tile server, which a
 * hospital network may not be able to reach and which would put a basemap
 * under a figure that does not need one. A district choropleth needs outlines
 * and a projection, and those are thirty lines.
 */

/* ------------------------------------------------------------- projection
 *
 * Spherical Mercator, then a single scale factor fitted to the bounding box so
 * the shapes keep their aspect ratio. Busoga spans about a degree, where the
 * difference between Mercator and plain equirectangular is invisible, but
 * getting it right costs one logarithm and means the same component would not
 * quietly distort a region further from the equator.
 */

/* How tall the figure may grow, and how much room the legend needs to sit
   beside it rather than beneath. Both are here rather than buried in the
   layout arithmetic because they are the two numbers anyone adjusting the
   map's size will want. */
const MAX_FIGURE_H = 1040;
const LEGEND_MIN_W = 170;
// Below this width a district's name will not fit inside it, so the label is
// dropped rather than spilled across a neighbour.
const MIN_LABEL_W = 34;

function mercatorY(lat) {
  const clamped = Math.max(-85, Math.min(85, lat));
  return (Math.log(Math.tan(Math.PI / 4 + (clamped * Math.PI) / 360)) * 180) / Math.PI;
}

function makeProjection(bbox, width, height, pad = 8) {
  const [minX, minY, maxX, maxY] = bbox;
  const y0 = mercatorY(minY);
  const y1 = mercatorY(maxY);
  const spanX = Math.max(maxX - minX, 1e-9);
  const spanY = Math.max(y1 - y0, 1e-9);
  const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY);
  // Centre whatever slack the aspect ratio leaves over.
  const offX = (width - spanX * scale) / 2;
  const offY = (height - spanY * scale) / 2;
  return ([lon, lat]) => [
    offX + (lon - minX) * scale,
    // SVG y grows downward; latitude grows upward.
    height - offY - (mercatorY(lat) - y0) * scale,
  ];
}

function ringPath(ring, project) {
  let d = '';
  for (let i = 0; i < ring.length; i++) {
    const [x, y] = project(ring[i]);
    d += `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
  }
  return `${d}Z`;
}

function shapePath(geometry, project) {
  const polys = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
  // Every ring of every polygon in one path, with fill-rule evenodd so an
  // interior ring reads as a hole rather than a second island.
  return polys.map((rings) => rings.map((r) => ringPath(r, project)).join('')).join('');
}

/* Where a district's name goes, and whether it fits.
 *
 * The centroid of the LARGEST ring, not of the whole geometry: Namayingo's
 * islands in Lake Victoria would otherwise drag its label into the water, and
 * a district whose name floats off its own shape is worse than an unlabelled
 * one. The ring's own bounding box then says whether the name fits inside it.
 */
function ringArea(ring) {
  let a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    a += (ring[j][0] * ring[i][1]) - (ring[i][0] * ring[j][1]);
  }
  return Math.abs(a / 2);
}

function labelPlacement(geometry, project) {
  const polys = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
  let best = null;
  polys.forEach((rings) => {
    const outer = rings[0];
    if (!outer || outer.length < 3) return;
    const area = ringArea(outer);
    if (!best || area > best.area) best = { area, ring: outer };
  });
  if (!best) return null;

  const pts = best.ring.map((c) => project(c));
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  // The area centroid of the projected ring, which sits inside any shape that
  // is not badly concave; the bounding-box centre is the fallback for those.
  let twice = 0, cx = 0, cy = 0;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i, i += 1) {
    const cross = (pts[j][0] * pts[i][1]) - (pts[i][0] * pts[j][1]);
    twice += cross;
    cx += (pts[j][0] + pts[i][0]) * cross;
    cy += (pts[j][1] + pts[i][1]) * cross;
  }
  const boxW = Math.max(...xs) - Math.min(...xs);
  const boxH = Math.max(...ys) - Math.min(...ys);
  const centre = Math.abs(twice) > 1e-6
    ? [cx / (3 * twice), cy / (3 * twice)]
    : [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
  return { x: centre[0], y: centre[1], width: boxW, height: boxH };
}

/* ------------------------------------------------------------------ colour
 *
 * Sequential, so one hue light to dark - never a rainbow. Lightness descends
 * monotonically (OKLab L 0.955 / 0.869 / 0.741 / 0.610 / 0.431), which is what
 * makes the order readable in greyscale and to a colourblind reader alike.
 *
 * "No data" is a diagonal hatch rather than another shade. A grey pale enough
 * not to compete with the dark end of the ramp sits within 0.03 lightness of
 * the palest blue, and "nobody reported" must never be mistakable for "the
 * lowest band" - the difference between a district that filed badly and one
 * that did not file at all.
 */
const RAMP = ['#e8f1fc', '#bcd7f4', '#7cb0e5', '#3b86d4', '#0a4f96'];
const NO_DATA = 'url(#nodata)';

/** Fixed bands for a percentage. The same colour means the same rate in every
 *  period, so two months can be compared; a quantile scheme recolours the
 *  survivors whenever the data shifts and makes that impossible. */
const PERCENT_BREAKS = [50, 70, 90];

function quantileBreaks(values, classes = 4) {
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length < classes) return null;
  const out = [];
  for (let i = 1; i < classes; i++) {
    out.push(sorted[Math.floor((i / classes) * sorted.length)]);
  }
  // Ties can collapse two breaks onto the same number, which would render an
  // empty band in the legend.
  return out.every((v, i) => i === 0 || v > out[i - 1]) ? out : null;
}

function equalBreaks(min, max, classes = 4) {
  if (!(max > min)) return null;
  const step = (max - min) / classes;
  return Array.from({ length: classes - 1 }, (_, i) => min + step * (i + 1));
}

function buildScale({ kind, values, min, max, mode }) {
  const nums = Object.values(values);
  let breaks = null;
  if (mode === 'quantile') breaks = quantileBreaks(nums);
  else if (kind === 'percent') breaks = PERCENT_BREAKS;
  else breaks = equalBreaks(min, max);
  if (!breaks) breaks = quantileBreaks(nums) || equalBreaks(min, max);

  // Four breaks-worth of bands from a five-step ramp keeps the palest step for
  // the lowest band and the darkest for the highest.
  const steps = breaks ? RAMP.slice(0, breaks.length + 1) : [RAMP[2]];
  const colourOf = (v) => {
    if (v === null || v === undefined) return NO_DATA;
    if (!breaks) return steps[0];
    let i = 0;
    while (i < breaks.length && v >= breaks[i]) i++;
    return steps[i];
  };
  return { breaks, steps, colourOf };
}

const fmt = (v, unit) => {
  if (v === null || v === undefined) return 'No data';
  const n = unit === '%' ? `${Number(v).toFixed(1)}%` : Number(v).toLocaleString('en-GB');
  return n;
};

const bandLabel = (breaks, steps, i, unit) => {
  const round = (v) => (unit === '%' ? Math.round(v) : Math.round(v).toLocaleString('en-GB'));
  if (i === 0) return `< ${round(breaks[0])}${unit}`;
  if (i === steps.length - 1) return `${round(breaks[breaks.length - 1])}${unit} +`;
  return `${round(breaks[i - 1])}–${round(breaks[i])}${unit}`;
};

/* -------------------------------------------------------------- component */

export default function DistrictMap({ homeDistrictOnly = false }) {
  const [geo, setGeo] = useState(null);
  const [catalogue, setCatalogue] = useState(null);
  const [indicator, setIndicator] = useState('');
  const [period, setPeriod] = useState('');
  const [mode, setMode] = useState('fixed');
  const [values, setValues] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [hover, setHover] = useState(null);
  const box = useRef(null);
  const width = useWidth(box, 640);

  // Outlines and the catalogue are both stable; fetch them once, together.
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const [g, c] = await Promise.all([
          fetch('/api/py/map/geometry').then(async (r) => {
            const b = await r.json().catch(() => null);
            if (!r.ok) throw new Error(b?.detail || `Outlines unavailable (HTTP ${r.status}).`);
            return b;
          }),
          fetch('/api/py/map/indicators').then(async (r) => {
            const b = await r.json().catch(() => null);
            if (!r.ok) throw new Error(b?.detail || `Indicator list unavailable (HTTP ${r.status}).`);
            return b;
          }),
        ]);
        if (!live) return;
        setGeo(g);
        setCatalogue(c);
        const first = c.groups?.[0]?.items?.[0];
        if (first) {
          setIndicator(first.id);
          setPeriod(c.periods?.[first.periodType]?.[0]?.period || '');
        }
      } catch (e) {
        if (live) setError(e.message);
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => { live = false; };
  }, []);

  const allItems = useMemo(
    () => (catalogue?.groups || []).flatMap((g) => g.items),
    [catalogue],
  );
  const chosen = allItems.find((i) => i.id === indicator) || null;
  const periodList = catalogue?.periods?.[chosen?.periodType || 'Monthly'] || [];

  // Changing the indicator can change the cadence, and a monthly period is not
  // a valid week. Move the period to the newest one of the new cadence rather
  // than sending DHIS2 something it will reject.
  useEffect(() => {
    if (!chosen || !periodList.length) return;
    if (!periodList.some((p) => p.period === period)) setPeriod(periodList[0].period);
  }, [chosen, periodList, period]);

  const load = useCallback(async () => {
    if (!indicator || !period) return;
    setBusy(true);
    setError('');
    try {
      const r = await fetch(
        `/api/py/map/values?indicator=${encodeURIComponent(indicator)}&period=${encodeURIComponent(period)}`);
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(b?.detail || `District figures unavailable (HTTP ${r.status}).`);
      setValues(b);
    } catch (e) {
      setValues(null);
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [indicator, period]);

  useEffect(() => { load(); }, [load]);

  /* Size the drawing to the region's own proportions, not the container's.
     Busoga is tall and narrow - Namayingo runs a long way south - so an SVG
     stretched to the full width of a card would put the districts in a thin
     strip down the middle with most of the card empty. The figure gets the
     shape it actually is, and the legend moves into the space beside it when
     there is room for it. */
  const aspect = useMemo(() => {
    if (!geo?.bbox) return 1;
    const [minX, minY, maxX, maxY] = geo.bbox;
    const spanY = mercatorY(maxY) - mercatorY(minY);
    return spanY > 0 ? (maxX - minX) / spanY : 1;
  }, [geo]);

  /* Height is the binding dimension, so the height budget is what to set.
     Deriving it from the card's WIDTH, as this did, gets the relationship
     backwards for a shape this narrow: in the dashboard tile a 482px card gave
     the figure 45 per cent of that as height, 217, raised to the 280 floor, and
     the aspect ratio then made it 136 wide. A map 136 by 288 sat beside a
     legend column of 346, so the key had two and a half times the width of the
     thing it was a key to.

     Take the height the card can reasonably carry instead, and let the aspect
     ratio set the width from it. The legend needs about 150px for its widest
     row ("This hospital's district"), so 170 is the threshold for keeping it
     alongside; below that it drops underneath, which is the right answer on a
     phone and the wrong one at 482px. */
  const { figureW, figureH, legendBeside } = useMemo(() => {
    // Fill the card's width, and let the aspect ratio set the height from it.
    // At the tile's 482px that draws the region 482 by 1021, about twice the
    // figure it replaced, which is what makes room for the district names.
    let w = width;
    let h = Math.round(w / aspect);
    if (h > MAX_FIGURE_H) { h = MAX_FIGURE_H; w = Math.round(h * aspect); }
    return { figureW: w, figureH: h, legendBeside: width - w > LEGEND_MIN_W };
  }, [width, aspect]);

  /* Type scales with the figure, but only between bounds: 11px is the floor at
     which a name is still readable, and past 15 the labels start to crowd the
     smaller districts out. */
  const labelSize = Math.max(11, Math.min(15, Math.round(figureW / 40)));

  const project = useMemo(
    () => (geo?.bbox ? makeProjection(geo.bbox, figureW, figureH) : null),
    [geo, figureW, figureH],
  );

  /* Name every district on the map itself. The names were only ever in the
     hover tooltip, which is no use to anyone reading a printed page, working
     from a screenshot in a report, or using a keyboard. */
  const placements = useMemo(() => {
    if (!project || !geo?.districts) return [];
    return geo.districts.map((d) => {
      const at = labelPlacement(d.geometry, project);
      if (!at) return null;
      // "Jinja District" reads as "Jinja" on a map of districts.
      const name = String(d.name || '').replace(/\s+district$/i, '').trim();
      return { id: d.id, name, ...at, fits: at.width >= MIN_LABEL_W };
    }).filter(Boolean);
  }, [geo, project]);
  const scale = useMemo(
    () => (values ? buildScale({ ...values, mode }) : null),
    [values, mode],
  );

  const shown = useMemo(() => {
    if (!geo) return [];
    if (!homeDistrictOnly) return geo.districts;
    return geo.districts;
  }, [geo, homeDistrictOnly]);

  if (loading) {
    return (
      <>
        <div className="loading-bar" style={{ marginBottom: '1rem' }} />
        <div className="text-secondary">Reading district outlines from DHIS2…</div>
      </>
    );
  }

  if (error && !geo) {
    return (
      <div className="empty">
        <div className="empty-title">The map could not be drawn</div>
        <div className="empty-subtitle">{error}</div>
      </div>
    );
  }

  const hovered = hover ? { ...hover, value: values?.values?.[hover.id] ?? null } : null;

  return (
    <>
      <div className="map-filters" style={{ marginBottom: '1rem' }}>
        <div>
          <label htmlFor="map-indicator">Indicator</label>
          <select id="map-indicator" value={indicator} onChange={(e) => setIndicator(e.target.value)}>
            {(catalogue?.groups || []).map((g) => (
              <optgroup key={g.group} label={g.group}>
                {g.items.map((i) => <option key={i.id} value={i.id}>{i.label}</option>)}
              </optgroup>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="map-period">Period</label>
          <select id="map-period" value={period} onChange={(e) => setPeriod(e.target.value)}>
            {periodList.map((p) => <option key={p.period} value={p.period}>{p.label}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="map-key">Key</label>
          <select id="map-key" value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="fixed">{chosen?.kind === 'percent' ? 'Fixed bands' : 'Equal intervals'}</option>
            <option value="quantile">Quantiles</option>
          </select>
          {/* The trade-off is the whole point of the control, so it is spelled
              out rather than left in a truncated option label. */}
          <div className="form-hint">
            {mode === 'quantile'
              ? 'Bands follow this period’s spread; colours shift between periods.'
              : chosen?.kind === 'percent'
                ? 'Same colour means the same rate in every period.'
                : 'Four equal steps across this period’s range.'}
          </div>
        </div>
      </div>

      {error && <div className="alert warn">{error}</div>}
      {busy && <div className="loading-bar" style={{ marginBottom: '.75rem' }} />}

      <div ref={box} className={`map-body ${legendBeside ? 'beside' : ''}`}>
      <div className="map-figure" style={{ width: figureW, flex: 'none' }}>
        <svg viewBox={`0 0 ${figureW} ${figureH}`} width={figureW} height={figureH} role="img"
          aria-label={`${chosen?.label || 'Indicator'} by district, ${
            periodList.find((p) => p.period === period)?.label || period}`}>
          <defs>
            {/* Texture, not a shade: "no data" must never be mistaken for the
                lowest band. */}
            <pattern id="nodata" width="6" height="6" patternUnits="userSpaceOnUse"
              patternTransform="rotate(45)">
              <rect width="6" height="6" fill="#f3f4f6" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="#c9ced6" strokeWidth="1.5" />
            </pattern>
          </defs>

          {project && shown.map((d) => (
            <path
              key={d.id}
              className="district"
              d={shapePath(d.geometry, project)}
              fill={scale ? scale.colourOf(values.values[d.id] ?? null) : '#f3f4f6'}
              fillRule="evenodd"
              onMouseEnter={() => setHover({ id: d.id, name: d.name })}
              onMouseLeave={() => setHover(null)}
            >
              <title>{`${d.name}: ${fmt(values?.values?.[d.id] ?? null, values?.unit || '')}`}</title>
            </path>
          ))}

          {project && geo.facilityDistrict && shown
            .filter((d) => d.id === geo.facilityDistrict)
            .map((d) => (
              <path key={`${d.id}-home`} className="home" d={shapePath(d.geometry, project)}
                fillRule="evenodd" />
            ))}

          {/* The names, last so nothing is drawn over them. paint-order puts
              the halo stroke behind the glyphs, which is what keeps a name
              readable over the darkest band of the ramp as well as the palest;
              black-on-white with a white halo needs no colour of its own. */}
          {placements.filter((pl) => pl.fits).map((pl) => (
            <text key={`${pl.id}-label`} x={pl.x} y={pl.y} textAnchor="middle"
              fontSize={labelSize} fontWeight={pl.id === geo.facilityDistrict ? 700 : 500}
              fill="#181818" stroke="#ffffff" strokeWidth="3" paintOrder="stroke"
              style={{ pointerEvents: 'none' }}>
              {pl.name}
            </text>
          ))}
        </svg>

        {hovered && (
          <div style={{
            position: 'absolute', top: 8, left: 8, pointerEvents: 'none',
            background: '#fff', border: '1px solid rgba(4,32,69,.1)', borderRadius: 6,
            boxShadow: '0 16px 24px 2px rgba(0,0,0,.07)', padding: '.5rem .625rem',
            fontSize: '.75rem', zIndex: 2,
          }}>
            <div className="fw-bold">{hovered.name}</div>
            <div className="text-secondary">
              {chosen?.label}: <span className="fw-medium">{fmt(hovered.value, values?.unit || '')}</span>
            </div>
          </div>
        )}
      </div>

      <div className={`map-legend ${legendBeside ? 'column' : ''}`}>
        {scale?.breaks
          ? scale.steps.map((c, i) => (
            <span key={c} className="swatch">
              <i style={{ background: c }} />
              {bandLabel(scale.breaks, scale.steps, i, values.unit)}
            </span>
          ))
          : <span className="text-secondary">No figures to band for this period.</span>}
        <span className="swatch">
          <i style={{
            backgroundImage:
              'repeating-linear-gradient(45deg,#f3f4f6 0 2px,#c9ced6 2px 3.5px)',
          }} />
          No data
        </span>
        {geo?.facilityDistrict && (
          <span className="swatch">
            <i style={{ background: 'transparent', boxShadow: 'inset 0 0 0 2px var(--tblr-body-color)' }} />
            This hospital&rsquo;s district
          </span>
        )}
      </div>
      </div>

      {geo?.withoutGeometry?.length > 0 && (
        <p className="text-secondary" style={{ fontSize: '.75rem', marginTop: '.625rem', marginBottom: 0 }}>
          Not drawn — no boundary stored in DHIS2: {geo.withoutGeometry.join(', ')}.
        </p>
      )}
    </>
  );
}
