import { useRef } from 'react';
import { useTranslation } from '../../../i18n';
import { useInlineSelection } from './useInlineSelection';

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
  useInlineSelection(strip, 'button[aria-current]');
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
