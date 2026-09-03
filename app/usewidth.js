'use client';
import { useEffect, useState } from 'react';

/**
 * The rendered pixel width of an element, for use as an SVG's viewBox width.
 *
 * A fixed viewBox scaled to fit its container scales *everything* with it, type
 * and stroke weights included. On a full-width layout that puts 11px axis
 * labels at 24px. Matching the viewBox to the measured width instead makes one
 * user unit one CSS pixel, so a label is the size it says it is on a laptop and
 * on a wall display alike.
 *
 * The fallback matters: ResizeObserver has not fired on the first paint, and
 * does not exist at all during the server render.
 */
export default function useWidth(ref, fallback = 760) {
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
