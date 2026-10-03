import type { Activity } from '../../api/types';
import type { TableActivityColumn } from '../../model/activityColumns';
import { activityText, activityValueText } from '../../model/presentation';

export function ActivityValueCell({
  displayId,
  column,
  activities,
  onSource,
}: {
  displayId: string;
  column: TableActivityColumn;
  activities: Activity[];
  onSource: (activity: Activity) => void;
}) {
  return (
    <td className="activity-value-column" data-activity-column={column.id}>
      {activities.length ? (
        <div className="activity-list">
          {activities.map((activity, index) => (
            <div className="activity-observation" key={index}>
              <span className="activity-value" title={activityText(activity)}>
                {activityValueText(activity)}
              </span>
              <button
                type="button"
                className="activity-source"
                disabled={activity.page === null}
                aria-label={`${displayId} ${activity.name} 活性来源${activity.page === null ? '页码未知' : `第 ${activity.page} 页`}`}
                title={`${activity.target ?? '靶点未知'} · ${activity.assay ?? '实验未知'}`}
                onClick={() => onSource(activity)}
              >
                {activity.page === null ? '来源未知' : `p.${activity.page}`}
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
