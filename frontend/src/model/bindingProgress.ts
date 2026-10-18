import type { BindingSourcePhase, Stage } from '../api/types';
import { t } from '../i18n';

const labels: Record<BindingSourcePhase, string> = {
  caption_sources: '核对图注',
  numbered_sources: '核对表格来源',
  numbered_cells: '核对编号单元格',
  declaration_sources: '核对原文声明',
  visible_captions: '核对图中编号',
  reference_sources: '核对表征引用',
  heading_sources: '核对原文标题',
  heading_bindings: '核对编号归属',
};

/** Real visited source work only; never molecule count, acceptance or an ETA. */
export function bindingProgressText(stage: Stage | undefined): string | null {
  const progress = stage?.progress;
  const phase = progress?.source_phase;
  if (stage?.name !== 'bind' || !progress || !phase) return null;
  return t(
    phase === 'heading_bindings'
      ? '{phase} · {completed} / {total} 项'
      : '{phase} · {completed} / {total} 页',
    { phase: t(labels[phase]), completed: progress.completed, total: progress.total },
  );
}
