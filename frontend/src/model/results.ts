import type { Compound, CompoundRecognition } from '../api/types';

export type ResultDensity = 'compact' | 'comfortable';

export function availableMetrics(metrics: string[], rows: Compound[]): string[] {
  return [
    ...new Set([...metrics, ...rows.flatMap((row) => row.activities.map((item) => item.name))]),
  ];
}

const recognitionLabels: Record<CompoundRecognition['status'], string> = {
  not_run: '尚未识别',
  valid: 'RDKit 可解析',
  invalid: 'RDKit 无效',
  unavailable: '识别不可用',
};
export function recognitionText(recognition: CompoundRecognition | null): string {
  if (recognition?.stereochemistry?.status === 'conflict') return '手性冲突';
  if (recognition?.stereochemistry?.status === 'ambiguous') return '手性待核对';
  if (recognition?.quality_flag === 'stereo_source_unavailable') return '手性证据不可用';
  return recognition ? recognitionLabels[recognition.status] : '识别状态未知';
}

export function redrawPlaceholder(compound: Compound): string {
  if (!compound.smiles?.trim()) return '未提供 SMILES，无法重绘';
  if (compound.recognition?.quality_flag?.startsWith('stereo_source_'))
    return '原图手性与模型结果未能一致，需修正后重绘';
  if (
    compound.recognition?.status === 'invalid' &&
    !(compound.correction?.has_changes && !compound.correction.stale)
  )
    return 'SMILES 未通过 RDKit 校验，无法重绘';
  return '重绘图片未提供（生成状态未知）';
}
