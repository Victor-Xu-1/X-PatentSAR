import { useLayoutEffect, type ReactNode } from 'react';
import { useTranslation } from '../../../i18n';
import { preferredScrollBehavior } from '../../../model/motion';
import { useScrollFocus } from '../../../components/useScrollFocus';

/** One bounded reference viewport, including multiple original reference graphs. */
export function StudyReferencePane({ active, children }: { active: boolean; children: ReactNode }) {
  const { t } = useTranslation();
  const { viewport, content } = useScrollFocus<HTMLElement, HTMLDivElement>('y', active);
  useLayoutEffect(() => {
    const pane = viewport.current;
    if (!pane || !active) return;
    pane.addEventListener('keydown', scrollBoundary);
    return () => {
      pane.removeEventListener('keydown', scrollBoundary);
    };
  }, [active, viewport]);
  return (
    <section ref={viewport} aria-label={t('参考结构')} className="sar-reference-maps">
      <div ref={content} className="sar-reference-map-content">
        {children}
      </div>
    </section>
  );
}

function scrollBoundary(event: KeyboardEvent) {
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
  const pane = event.currentTarget as HTMLElement;
  pane.scrollTo({
    top: event.key === 'Home' ? 0 : pane.scrollHeight,
    behavior: preferredScrollBehavior(),
  });
}
