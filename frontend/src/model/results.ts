import type { Activity, Compound, CompoundRecognition } from '../api/types';

export type ResultDensity = 'compact' | 'comfortable';
export interface AssayContext {
  key: string;
  target: string | null;
  assay: string | null;
  activities: Activity[];
}

export function availableMetrics(metrics: string[], rows: Compound[]): string[] {
  return [
    ...new Set([...metrics, ...rows.flatMap((row) => row.activities.map((item) => item.name))]),
  ];
}

export function groupActivities(activities: Activity[], metrics: string[]): AssayContext[] {
  const visible = new Set(metrics);
  const groups = new Map<string, AssayContext>();
  for (const activity of activities) {
    if (!visible.has(activity.name)) continue;
    // Page is measurement provenance, not shared assay metadata. Never borrow a group page.
    const key = JSON.stringify([activity.target, activity.assay]);
    const group = groups.get(key) ?? {
      key,
      target: activity.target,
      assay: activity.assay,
      activities: [],
    };
    group.activities.push(activity);
    groups.set(key, group);
  }
  return [...groups.values()];
}

const recognitionLabels: Record<CompoundRecognition['status'], string> = {
  not_run: '尚未识别',
  valid: 'RDKit 可解析',
  invalid: 'RDKit 无效',
  unavailable: '识别不可用',
};
export function recognitionText(recognition: CompoundRecognition | null): string {
  return recognition ? recognitionLabels[recognition.status] : '识别状态未知';
}

export function redrawPlaceholder(compound: Compound): string {
  if (!compound.smiles?.trim()) return '未提供 SMILES，无法重绘';
  if (compound.recognition?.status === 'invalid') return 'SMILES 未通过 RDKit 校验，无法重绘';
  return '重绘图片未提供（生成状态未知）';
}
