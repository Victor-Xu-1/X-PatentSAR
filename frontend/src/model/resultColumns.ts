import { METRIC_SPECS } from '../api/predictionTypes';
import type { LeadAssessment } from '../api/leadTypes';
import { activityColumnContext, activityColumnLabel } from './activityColumns';
import type { TableActivityColumn } from './activityColumns';
import { strengthScaleText } from './activityStrength';

export interface ResultColumn {
  id: string;
  label: string;
  className: string;
  width: number;
  min: number;
  max: number;
  context?: string;
  details?: string;
  hint?: string;
}

const column = (
  id: string,
  label: string,
  className: string,
  width: number,
  min: number,
  max: number,
): ResultColumn => ({ id, label, className, width, min, max });

// Empty is a true spreadsheet/query blank, not an inactive-compound claim.
export function leadColumnValue(assessment: LeadAssessment | null | undefined): string {
  return assessment?.status === 'selected' &&
    assessment.rank !== null &&
    Number.isInteger(assessment.rank) &&
    assessment.rank >= 1 &&
    assessment.rank <= 10
    ? `Lead ${assessment.rank}`
    : '';
}

export function resultColumns(activities: TableActivityColumn[] = []): ResultColumn[] {
  const counts = new Map<string, number>();
  for (const activity of activities)
    counts.set(activity.name, (counts.get(activity.name) ?? 0) + 1);
  return [
    column('select', '选择', 'check-col frozen-column frozen-select', 38, 38, 100),
    column('compound', 'Compound', 'compound-column frozen-column frozen-compound', 120, 88, 480),
    column('structure', '结构', 'structure-column frozen-column frozen-structure', 136, 88, 480),
    {
      ...column('lead', 'Lead', 'lead-column', 88, 72, 240),
      hint: '全项目研究候选排序；评分、依据与警告见单元格提示，不代表实验验证。',
    },
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
      ...(activity.strength_scale ? { hint: strengthScaleText(activity.strength_scale) } : {}),
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
      column(`property:${spec.key}`, spec.label, 'prediction-column', 88, 64, 180),
    ),
    column('source', '原文', 'source-column', 64, 48, 180),
    column('edit', '修正', 'edit-column frozen-column frozen-edit', 64, 40, 120),
  ];
}
