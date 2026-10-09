import { useEffect, useRef } from 'react';
import { useTranslation } from '../../../i18n';

export function StudyViewTabs({
  labels,
  selected,
  panelId,
  onSelect,
}: {
  labels: readonly string[];
  selected: number;
  panelId: string;
  onSelect: (index: number) => void;
}) {
  const { t } = useTranslation();
  const strip = useRef<HTMLElement>(null);
  // Scroll only this strip, including programmatic source/table navigation or a
  // language change. Do not move the document or change the selected result.
  useEffect(() => {
    const element = strip.current;
    const current = element?.querySelector<HTMLElement>('button[aria-current]');
    if (!element || !current) return;
    const bounds = element.getBoundingClientRect(),
      choice = current.getBoundingClientRect();
    if (choice.left < bounds.left) element.scrollLeft -= bounds.left - choice.left;
    else if (choice.right > bounds.right) element.scrollLeft += choice.right - bounds.right;
  });
  return (
    <nav ref={strip} className="sar-study-tabs" aria-label={t('研究视图')}>
      {labels.map((label, index) => (
        <button
          key={label}
          type="button"
          aria-current={selected === index ? 'page' : undefined}
          aria-controls={panelId + '-' + index}
          onClick={() => onSelect(index)}
        >
          {t(label)}
        </button>
      ))}
    </nav>
  );
}
