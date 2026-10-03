import type { Compound } from '../../api/types';
import { useId } from 'react';
import type {
  ActivityObservation,
  ActivitySourceCallback,
  TableActivityColumn,
} from '../../model/activityColumns';
import { activityText, activityValueText } from '../../model/presentation';
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
          {observations.map(({ activity, index, sourceKey }, position) => (
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
                aria-label={`${row.display_id} ${activity.name} 活性来源${activity.page === null ? '页码未知' : `第 ${activity.page} 页`}`}
                title={
                  scale
                    ? `${activityText(activity)} · ${activityStrengthLabels[tiers[position]!]}；${strengthScaleText(scale)}`
                    : activityText(activity)
                }
                aria-describedby={scale ? `${descriptionId}-${index}` : undefined}
                onClick={() => onSource(row, activity, sourceKey)}
              >
                {activityValueText(activity)}
              </button>
              {scale && (
                <span id={`${descriptionId}-${index}`} className="sr-only">
                  {activityStrengthLabels[tiers[position]!]}
                  ；仅本列全项目相对排序，不代表绝对活性或验收。
                </span>
              )}
            </div>
          ))}
        </div>
      ) : (
        <span className="muted" aria-label={`${column.name} 该指标无数据`}>
          —
        </span>
      )}
    </td>
  );
}
