import { METRIC_SPECS } from '../api/predictionTypes';

export interface ResultColumn {
  id: string;
  label: string;
  className: string;
  width: number;
  min: number;
  max: number;
}

const column = (
  id: string,
  label: string,
  className: string,
  width: number,
  min: number,
  max: number,
): ResultColumn => ({ id, label, className, width, min, max });

export function resultColumns(): ResultColumn[] {
  return [
    column('select', '选择', 'check-col', 38, 38, 100),
    column('number', '序号', 'number-column', 32, 28, 150),
    column('structure', '结构 / 编号', 'structure-column', 164, 120, 480),
    column('activities', '专利活性', 'activity-summary-column', 270, 180, 720),
    ...METRIC_SPECS.map((spec) =>
      column(`property:${spec.key}`, spec.label, 'prediction-column', 64, 48, 180),
    ),
    column('source', '原文', 'source-column', 64, 48, 180),
    column('edit', '修正', 'edit-column', 48, 40, 120),
  ];
}
