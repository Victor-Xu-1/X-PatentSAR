import { useTranslation } from '../../i18n';
import type { Compound } from '../../api/types';
import { useId } from 'react';
import type {
  ActivityObservation,
  ActivitySourceCallback,
  TableActivityColumn,
} from '../../model/activityColumns';
import { activityValueText } from '../../model/presentation';
import { compoundLabel } from '../../model/compoundLabel';
import {
  activityStrength,
  activityStrengthLabels,
  strengthScaleText,
} from '../../model/activityStrength';

export function ActivityValueCell({
  row,
  column,
  observations,
  onSource,
}: {
  row: Compound;
  column: TableActivityColumn;
  observations: ActivityObservation[];
  onSource: ActivitySourceCallback;
}) {
  const { t } = useTranslation();
  const scale = column.strength_scale;
  const descriptionId = useId();
  const tiers = observations.map(({ index }) =>
    activityStrength(row.activity_rank_values?.[index], scale),
  );
  const uniform = new Set(tiers).size === 1 ? tiers[0] : undefined;
  return (
    <td
      className="activity-value-column"
      data-activity-column={column.id}
      data-activity-strength={uniform}
    >
      {observations.length ? (
        <div className="activity-list">
          {observations.map(({ activity, index, sourceKey }, position) => {
            const value = activity.value === null ? t('值未提供') : activityValueText(activity);
            const heading = `${activity.name || t('活性')} = ${value}`;
            return (
              <div
                className="activity-observation"
                key={index}
                data-activity-strength={tiers[position]}
              >
                <button
                  type="button"
                  className="activity-value activity-source"
                  data-activity-index={index}
                  data-activity-source-key={sourceKey}
                  disabled={activity.page === null}
                  aria-label={
                    activity.page === null
                      ? t('{label} {activity} 活性来源页码未知', {
                          label: compoundLabel(row),
                          activity: activity.name,
                        })
                      : t('{label} {activity} 活性来源第 {page} 页', {
                          label: compoundLabel(row),
                          activity: activity.name,
                          page: activity.page,
                        })
                  }
                  title={
                    scale
                      ? t('{activity} · {tier}；{scale}', {
                          activity: heading,
                          tier: t(activityStrengthLabels[tiers[position]!]),
                          scale: strengthScaleText(scale),
                        })
                      : heading
                  }
                  aria-describedby={scale ? `${descriptionId}-${index}` : undefined}
                  onClick={() => onSource(row, activity, sourceKey)}
                >
                  {value}
                </button>
                {scale && (
                  <span id={`${descriptionId}-${index}`} className="sr-only">
                    {t('{tier}；仅本列全项目相对排序，不代表绝对活性或验收。', {
                      tier: t(activityStrengthLabels[tiers[position]!]),
                    })}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <span className="muted" aria-label={t('{column} 该指标无数据', { column: column.name })}>
          —
        </span>
      )}
    </td>
  );
}
