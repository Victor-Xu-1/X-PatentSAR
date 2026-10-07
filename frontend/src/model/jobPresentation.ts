import type { Job } from '../api/types';
import {
  observedStages,
  recognitionReviewCount,
  stageLabel,
  stageProgressText,
  waitingResources,
} from './extraction';

/** A short read-only description; the full recorded failure stays in task details. */
export function jobRecordSummary(job: Job): string | null {
  if (job.status === 'failed' && job.error?.code === 'core_not_accepted') {
    const count = recognitionReviewCount(job);
    return count === null
      ? '核心校验未通过，结果需复核。'
      : `核心校验未通过，${count} 条结构需复核。`;
  }
  if (job.status === 'interrupted')
    return job.can_resume ? '任务已中断，可继续提取。' : '任务已中断，恢复状态见任务详情。';
  if (job.status === 'failed')
    return job.error ? '运行失败，原因见任务详情。' : '运行失败，服务端未提供原因。';
  if (job.error) return '任务报告了错误，原因见任务详情。';
  if (job.status !== 'running') return null;
  if (job.history_available !== true)
    return job.history_available === false ? '历史阶段不可用。' : '阶段状态未知。';
  const stage = observedStages(job).find(
    (value) => value.status === 'running' || waitingResources(job, value),
  );
  if (!stage) return null;
  const observation = waitingResources(job, stage) ? '等待资源' : stageProgressText(stage);
  return `${stageLabel(stage.name, stage)}${observation ? ` · ${observation}` : ''}`;
}
