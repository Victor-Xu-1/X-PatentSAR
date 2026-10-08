import { useTranslation } from '../../i18n';
import type { ActivityBand, FilterValues } from '../../api/types';

const labels: Record<ActivityBand, string> = { strong: '强档', medium: '中档', none: '无填充' };
export function ColumnBandChoices({
  bands,
  selected,
  disabled,
  action,
  onChoose,
}: {
  bands: FilterValues['bands'];
  selected?: ActivityBand | '' | undefined;
  disabled: boolean;
  action: '排序' | '筛选';
  onChoose: (band: ActivityBand) => void;
}) {
  const { t } = useTranslation();
  return (
    <fieldset
      className="column-band-choices"
      aria-label={t(action === '筛选' ? '按颜色筛选' : '按颜色排序')}
    >
      {bands?.map((band) => (
        <button
          type="button"
          key={band.value}
          aria-label={t(action === '筛选' ? '{band}筛选' : '{band}优先', {
            band: t(labels[band.value]),
          })}
          aria-pressed={selected === band.value}
          disabled={disabled}
          onClick={() => onChoose(band.value)}
        >
          <span
            className="column-band-swatch"
            data-activity-strength={band.value}
            aria-hidden="true"
          />
          <span>{t(labels[band.value])}</span>
          <small>{band.count}</small>
        </button>
      ))}
      {!bands?.length && <small className="muted">{t('颜色分档不可用')}</small>}
    </fieldset>
  );
}
