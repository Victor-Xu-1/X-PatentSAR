import { useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { useTranslation } from '../../../i18n';
import { preferredScrollBehavior } from '../../../model/motion';

/** One bounded reference viewport, including multiple original reference graphs. */
export function StudyReferencePane({ active, children }: { active: boolean; children: ReactNode }) {
  const { t } = useTranslation();
  const viewport = useRef<HTMLElement>(null);
  const content = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const pane = viewport.current,
      body = content.current;
    if (!pane || !body) return;
    pane.tabIndex = -1;
    if (!active) return;
    const measure = () => {
      pane.tabIndex = pane.scrollHeight > pane.clientHeight + 1 ? 0 : -1;
    };
    measure();
    if (typeof ResizeObserver !== 'function') return;
    let frame: number | null = null;
    const observer = new ResizeObserver(() => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        measure();
      });
    });
    observer.observe(pane);
    observer.observe(body);
    return () => {
      observer.disconnect();
      if (frame !== null) cancelAnimationFrame(frame);
      pane.tabIndex = -1;
    };
  }, [active]);
  return (
    <section
      ref={viewport}
      aria-label={t('参考结构')}
      className="sar-reference-maps"
      onKeyDown={scrollBoundary}
    >
      <div ref={content} className="sar-reference-map-content">
        {children}
      </div>
    </section>
  );
}

function scrollBoundary(event: KeyboardEvent<HTMLElement>) {
  if (
    event.target !== event.currentTarget ||
    event.altKey ||
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey ||
    !['Home', 'End'].includes(event.key)
  )
    return;
  event.preventDefault();
  event.currentTarget.scrollTo({
    top: event.key === 'Home' ? 0 : event.currentTarget.scrollHeight,
    behavior: preferredScrollBehavior(),
  });
}
