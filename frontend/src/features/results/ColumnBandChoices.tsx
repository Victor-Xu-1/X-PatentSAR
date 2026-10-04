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
  return (
    <fieldset className="column-band-choices" aria-label={`按颜色${action}`}>
      {bands?.map((band) => (
        <button
          type="button"
          key={band.value}
          aria-label={`${labels[band.value]}${action === '筛选' ? '筛选' : '优先'}`}
          aria-pressed={selected === band.value}
          disabled={disabled}
          onClick={() => onChoose(band.value)}
        >
          <span
            className="column-band-swatch"
            data-activity-strength={band.value}
            aria-hidden="true"
          />
          <span>{labels[band.value]}</span>
          <small>{band.count}</small>
        </button>
      ))}
      {!bands?.length && <small className="muted">颜色分档不可用</small>}
    </fieldset>
  );
}
