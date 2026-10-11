import { useLayoutEffect, useRef } from 'react';

/** Only overflowing native viewports need a keyboard stop; never move focus. */
export function useScrollFocus<Viewport extends HTMLElement, Content extends HTMLElement>(
  axis: 'x' | 'y',
  active = true,
) {
  const viewport = useRef<Viewport>(null);
  const content = useRef<Content>(null);
  useLayoutEffect(() => {
    const pane = viewport.current,
      body = content.current;
    if (!pane || !body) return;
    pane.tabIndex = -1;
    if (!active) return;
    const measure = () => {
      const overflow =
        axis === 'x'
          ? pane.scrollWidth > pane.clientWidth + 1
          : pane.scrollHeight > pane.clientHeight + 1;
      pane.tabIndex = overflow ? 0 : -1;
    };
    measure();
    let frame: number | null = null;
    const observer =
      typeof ResizeObserver === 'function'
        ? new ResizeObserver(() => {
            if (frame !== null) return;
            frame = requestAnimationFrame(() => {
              frame = null;
              measure();
            });
          })
        : null;
    observer?.observe(pane);
    observer?.observe(body);
    return () => {
      observer?.disconnect();
      if (frame !== null) cancelAnimationFrame(frame);
      pane.tabIndex = -1;
    };
  }, [active, axis]);
  return { viewport, content };
}
