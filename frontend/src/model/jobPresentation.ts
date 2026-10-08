import { t } from '../i18n';
import type { Job, Stage } from '../api/types';
import {
  observedStages,
  pageProgressStage,
  recognitionReviewCount,
  stageLabel,
  waitingResources,
} from './extraction';

/** Numeric observations stay unchanged; only their application-owned caption varies. */
export function jobStageProgressText(stage: Stage | undefined): string | null {
  const progress = stage?.progress;
  if (!stage || !progress) return null;
  const values = { completed: progress.completed, total: progress.total };
  if (pageProgressStage(stage.name))
    return t(
      stage.status === 'failed' ? '已处理 {completed} / {total} 页' : '{completed} / {total} 页',
      values,
    );
  return stage.status === 'failed'
    ? t('已处理 {completed} / {total}', values)
    : `${progress.completed} / ${progress.total}`;
}

/** A short read-only description; the full recorded failure stays in task details. */
export function jobRecordSummary(job: Job): string | null {
  if (job.status === 'failed' && job.error?.code === 'core_not_accepted') {
    const count = recognitionReviewCount(job);
    return count === null
      ? t('核心校验未通过，结果需复核。')
      : t('核心校验未通过，{count} 条结构需复核。', { count });
  }
  if (job.status === 'interrupted')
    return job.can_resume ? t('任务已中断，可继续提取。') : t('任务已中断，恢复状态见任务详情。');
  if (job.status === 'failed')
    return job.error ? t('运行失败，原因见任务详情。') : t('运行失败，服务端未提供原因。');
  if (job.error) return t('任务报告了错误，原因见任务详情。');
  if (job.status !== 'running') return null;
  if (job.history_available !== true)
    return job.history_available === false ? t('历史阶段不可用。') : t('阶段状态未知。');
  const stage = observedStages(job).find(
    (value) => value.status === 'running' || waitingResources(job, value),
  );
  if (!stage) return null;
  const observation = waitingResources(job, stage) ? t('等待资源') : jobStageProgressText(stage);
  return `${t(stageLabel(stage.name, stage))}${observation ? ` · ${observation}` : ''}`;
}
