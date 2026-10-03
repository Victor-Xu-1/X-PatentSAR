import type { Activity, Compound } from '../../api/types';
import { activityText, activityValueText } from '../../model/presentation';

export function ActivitySummary({
  row,
  metrics,
  onSource,
}: {
  row: Compound;
  metrics?: string[];
  onSource: (activity: Activity) => void;
}) {
  const activities = metrics
    ? row.activities.filter((activity) => metrics.includes(activity.name))
    : row.activities;
  const missingActivity = row.record_kind === 'structure_only' && row.activities.length === 0;
  return (
    <td className="activity-summary-column">
      <div className="activity-list">
        {activities.length ? (
          activities.map((activity, index) => (
            <div
              className="activity-observation"
              key={index}
              title={[activity.target, activity.assay].filter(Boolean).join(' · ')}
            >
              <span className="activity-name">{activity.name}</span>
              <span className="activity-value" title={activityText(activity)}>
                {activityValueText(activity)}
              </span>
              <button
                type="button"
                className="activity-source"
                disabled={activity.page === null}
                aria-label={`${row.display_id} ${activity.name} 活性来源${activity.page === null ? '页码未知' : `第 ${activity.page} 页`}`}
                title={`${activity.target ?? '靶点未知'} · ${activity.assay ?? '实验未知'}`}
                onClick={() => onSource(activity)}
              >
                {activity.page === null ? '来源未知' : `p.${activity.page}`}
              </button>
            </div>
          ))
        ) : (
          <span className="muted" aria-label={missingActivity ? '未关联活性' : '该指标无数据'}>
            {missingActivity ? '未关联活性' : '—'}
          </span>
        )}
      </div>
    </td>
  );
}
