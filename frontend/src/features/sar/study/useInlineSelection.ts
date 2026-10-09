import { useCallback, useEffect, useLayoutEffect } from 'react';
import type { RefObject } from 'react';

/** Reveal a selected control without scrolling the page or moving focus. */
export function useInlineSelection(ref: RefObject<HTMLElement | null>, selector: string) {
  const reveal = useCallback(() => {
    const strip = ref.current;
    const selected = strip?.querySelector<HTMLElement>(selector);
    if (!strip || !selected) return;
    const bounds = strip.getBoundingClientRect(),
      choice = selected.getBoundingClientRect();
    if (bounds.width <= 0 || choice.width <= 0) return;
    if (choice.left < bounds.left) strip.scrollLeft -= bounds.left - choice.left;
    else if (choice.right > bounds.right) strip.scrollLeft += choice.right - bounds.right;
  }, [ref, selector]);
  // Also handles source-driven selection and translated controls after render.
  useLayoutEffect(reveal);
  useEffect(() => {
    const strip = ref.current;
    if (!strip || typeof ResizeObserver !== 'function') return;
    let disposed = false,
      frame: number | null = null;
    const observer = new ResizeObserver(() => {
      if (disposed || frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        reveal();
      });
    });
    observer.observe(strip);
    return () => {
      disposed = true;
      observer.disconnect();
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [ref, reveal]);
}
