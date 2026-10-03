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

export function resultColumns(metrics: string[]): ResultColumn[] {
  return [
    column('select', '选择', 'check-col', 38, 38, 100),
    column('number', '序号', 'number-column', 32, 28, 150),
    column('structure', '原始结构 / 编号', 'structure-column', 142, 142, 480),
    column('context', '靶点 / 实验', 'context-column', 190, 120, 720),
    ...metrics.map((metric) =>
      column(`metric:${metric}`, metric || '未命名指标', 'activity-column', 128, 80, 640),
    ),
    column('evidence', '绑定证据', 'evidence-column', 82, 60, 300),
    column('recognition', '识别校验', 'recognition-column', 114, 96, 420),
    column('source', '结构来源', 'source-column', 104, 104, 380),
    column('review', '人工复核', 'review-column', 82, 64, 300),
  ];
}
