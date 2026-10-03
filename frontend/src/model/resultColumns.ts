import { METRIC_SPECS } from '../api/predictionTypes';
import { activityColumnContext, activityColumnLabel } from './activityColumns';
import type { TableActivityColumn } from './activityColumns';

export interface ResultColumn {
  id: string;
  label: string;
  className: string;
  width: number;
  min: number;
  max: number;
  context?: string;
  details?: string;
}

const column = (
  id: string,
  label: string,
  className: string,
  width: number,
  min: number,
  max: number,
): ResultColumn => ({ id, label, className, width, min, max });

export function resultColumns(activities: TableActivityColumn[] = []): ResultColumn[] {
  const counts = new Map<string, number>();
  for (const activity of activities)
    counts.set(activity.name, (counts.get(activity.name) ?? 0) + 1);
  return [
    column('select', '选择', 'check-col frozen-column frozen-select', 38, 38, 100),
    column('number', '序号', 'number-column frozen-column frozen-number', 32, 28, 150),
    column(
      'structure',
      '结构 / 编号',
      'structure-column frozen-column frozen-structure',
      164,
      120,
      480,
    ),
    ...activities.map((activity) => ({
      ...column(
        `activity:${activity.id}`,
        activityColumnLabel(activity),
        'activity-value-column',
        160,
        100,
        640,
      ),
      context: activityColumnContext(activity),
      details: [activity.target, activity.assay]
        .filter(
          (value): value is string =>
            value !== null &&
            value !== '' &&
            ((counts.get(activity.name) ?? 0) > 1 ||
              !activity.name.toLocaleLowerCase().includes(value.toLocaleLowerCase())),
        )
        .join(' · '),
    })),
    ...METRIC_SPECS.map((spec) =>
      column(`property:${spec.key}`, spec.label, 'prediction-column', 64, 48, 180),
    ),
    column('source', '原文', 'source-column', 64, 48, 180),
    column('edit', '修正', 'edit-column frozen-column frozen-edit', 48, 40, 120),
  ];
}
