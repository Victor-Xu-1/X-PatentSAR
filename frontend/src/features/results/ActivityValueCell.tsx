import type { Compound } from '../../api/types';
import type {
  ActivityObservation,
  ActivitySourceCallback,
  TableActivityColumn,
} from '../../model/activityColumns';
import { activityText, activityValueText } from '../../model/presentation';

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
  return (
    <td className="activity-value-column" data-activity-column={column.id}>
      {observations.length ? (
        <div className="activity-list">
          {observations.map(({ activity, index, sourceKey }) => (
            <div className="activity-observation" key={index}>
              <button
                type="button"
                className="activity-value activity-source"
                data-activity-index={index}
                data-activity-source-key={sourceKey}
                disabled={activity.page === null}
                aria-label={`${row.display_id} ${activity.name} 活性来源${activity.page === null ? '页码未知' : `第 ${activity.page} 页`}`}
                title={activityText(activity)}
                onClick={() => onSource(row, activity, sourceKey)}
              >
                {activityValueText(activity)}
              </button>
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
