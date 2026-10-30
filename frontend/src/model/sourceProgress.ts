import type { SourceWorkPhase, Stage } from '../api/types';
import { bindingSourcePhases, pageSourcePhases } from '../api/types';
import { t } from '../i18n';

const labels: Record<SourceWorkPhase, string> = {
  caption_sources: '核对图注',
  numbered_sources: '核对表格来源',
  numbered_cells: '核对编号单元格',
  declaration_sources: '核对原文声明',
  visible_captions: '核对图中编号',
  reference_sources: '核对表征引用',
  heading_sources: '核对原文标题',
  heading_bindings: '核对编号归属',
  page_ocr: '读取原始页面',
  empty_text_retry: '复读空文本观察',
  page_classification: '分析页面用途',
};

/** One source-work caption; never molecule counts, acceptance or estimated time. */
export function sourceProgressText(stage: Stage | undefined): string | null {
  const progress = stage?.progress;
  const phase = progress?.source_phase;
  if (!progress || !phase) return null;
  const owned =
    stage?.name === 'bind'
      ? bindingSourcePhases.some((value) => value === phase)
      : stage?.name === 'classify' && pageSourcePhases.some((value) => value === phase);
  if (!owned) return null;
  return t(
    phase === 'heading_bindings'
      ? '{phase} · {completed} / {total} 项'
      : '{phase} · {completed} / {total} 页',
    { phase: t(labels[phase]), completed: progress.completed, total: progress.total },
  );
}
