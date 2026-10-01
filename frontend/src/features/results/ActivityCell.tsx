import type { Activity, Compound } from '../../api/types';
import type { AssayContext } from '../../model/results';
import { activityText, activityValueText } from '../../model/presentation';

export function ActivityCell({
  compound,
  metric,
  contexts,
  onSource,
}: {
  compound: Compound;
  metric: string;
  contexts: AssayContext[];
  onSource: (activity: Activity) => void;
}) {
  const observations = contexts.flatMap((context, index) =>
    context.activities
      .filter((activity) => activity.name === metric)
      .map((activity) => ({ activity, context: index + 1 })),
  );
  return (
    <td className="activity-column" data-metric={metric}>
      <div className="activity-list">
        {observations.length ? (
          observations.map(({ activity, context }, index) => (
            <div className="activity-observation" key={index}>
              <span className="activity-value" title={activityText(activity)}>
                {activityValueText(activity)}
              </span>
              <button
                type="button"
                className="activity-source"
                aria-label={`${compound.display_id} ${metric} 活性来源${activity.page === null ? '页码未知' : `第 ${activity.page} 页`}`}
                title={
                  activity.page === null ? '活性来源页码未知' : `活性来源第 ${activity.page} 页`
                }
                disabled={activity.page === null}
                onClick={() => onSource(activity)}
              >
                {contexts.length > 1 && <span className="context-reference">{context} · </span>}
                {activity.page === null ? '来源未知' : `p.${activity.page}`}
              </button>
            </div>
          ))
        ) : (
          <span className="muted" title="该指标无数据" aria-label="该指标无数据">
            —
          </span>
        )}
      </div>
    </td>
  );
}
