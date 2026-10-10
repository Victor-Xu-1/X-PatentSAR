import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { useTranslation } from '../../../i18n';

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
    <section ref={viewport} aria-label={t('参考结构')} className="sar-reference-maps">
      <div ref={content} className="sar-reference-map-content">
        {children}
      </div>
    </section>
  );
}
