import { useCallback, useLayoutEffect, useRef, useState } from 'react';

/** Only overflowing native viewports need a keyboard stop; never move focus. */
export function useScrollFocus<Viewport extends HTMLElement, Content extends HTMLElement>(
  axis: 'x' | 'y',
  active = true,
) {
  const viewport = useRef<Viewport>(null);
  const content = useRef<Content>(null);
  const [edges, setEdges] = useState({ overflow: false, start: false, end: false });
  useLayoutEffect(() => {
    const pane = viewport.current,
      body = content.current;
    if (!pane || !body) return;
    pane.tabIndex = -1;
    const measure = () => {
      const extent = axis === 'x' ? pane.clientWidth : pane.clientHeight;
      const length = axis === 'x' ? pane.scrollWidth : pane.scrollHeight;
      const offset = axis === 'x' ? pane.scrollLeft : pane.scrollTop;
      const overflow = active && length > extent + 1;
      pane.tabIndex = overflow ? 0 : -1;
      const next = {
        overflow,
        start: overflow && offset > 1,
        end: overflow && offset + extent < length - 1,
      };
      setEdges((previous) =>
        previous.overflow === next.overflow &&
        previous.start === next.start &&
        previous.end === next.end
          ? previous
          : next,
      );
    };
    measure();
    if (!active) return;
    let frame: number | null = null;
    const schedule = () => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        measure();
      });
    };
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(schedule) : null;
    observer?.observe(pane);
    observer?.observe(body);
    pane.addEventListener('scroll', schedule, { passive: true });
    return () => {
      observer?.disconnect();
      pane.removeEventListener('scroll', schedule);
      if (frame !== null) cancelAnimationFrame(frame);
      pane.tabIndex = -1;
    };
  }, [active, axis]);
  const scrollPage = useCallback(
    (direction: -1 | 1) => {
      const pane = viewport.current;
      if (!pane) return;
      const distance = Math.max(
        1,
        Math.round((axis === 'x' ? pane.clientWidth : pane.clientHeight) * 0.8),
      );
      const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'auto'
        : 'smooth';
      pane.scrollBy({ [axis === 'x' ? 'left' : 'top']: direction * distance, behavior });
    },
    [axis],
  );
  return { viewport, content, edges, scrollPage };
}
