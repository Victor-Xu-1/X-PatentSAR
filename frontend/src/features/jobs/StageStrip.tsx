import { Check, CircleAlert, LoaderCircle } from 'lucide-react';
import type { Job } from '../../api/types';
import { jobStatusText } from '../../model/presentation';
import {
  completeCoreStages,
  completedCoreRejection,
  observedStages,
  recognitionReviewCount,
  reviewedCoreStage,
  stageLabel,
  stageProgressText,
  stageStatusText,
  stoppedJob,
  waitingAdmet,
  waitingResources,
  workflowStageNames,
} from '../../model/extraction';
import { StageObservation } from './StageObservation';

export function StageStrip({ job, compact = false }: { job: Job | null; compact?: boolean }) {
  const stages = observedStages(job);
  const names = workflowStageNames(job);
  const historyNotice =
    job && job.history_available !== true ? (
      <output className="stage-history-notice">
        {job.history_available === false
          ? '历史阶段不可用：本次任务的阶段记录无法可靠读取。'
          : '历史阶段可用性未知'}
      </output>
    ) : null;
  const list = (
    <ol className="stage-strip" aria-label="任务运行链路">
      {names.map((name, index) => {
        const stage = stages.find((item) => item.name === name);
        const label = stageLabel(name, stage);
        const status =
          job && job.history_available !== true
            ? 'unknown'
            : (stage?.status ??
              (name === 'admet' && !waitingAdmet(job, stage) ? 'unknown' : 'pending'));
        return (
          <li
            className={`stage ${status}${reviewedCoreStage(job, stage) ? ' needs-review' : ''}`}
            key={name}
            title={`${label}：${stageStatusText(job, stage, name)}`}
          >
            <span className="stage-circle">
              {status === 'ok' ? (
                <Check size={13} />
              ) : status === 'running' && !stoppedJob(job) ? (
                <LoaderCircle size={13} className="spin" />
              ) : status === 'failed' ? (
                <CircleAlert size={13} />
              ) : (
                index + 1
              )}
            </span>
            {job?.history_available === true ? (
              <StageObservation job={job} stage={stage} name={name} />
            ) : (
              <div>
                <strong>{label}</strong>
                <small>{stageStatusText(job, stage, name)}</small>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
  if (!compact)
    return (
      <div className="stage-overview">
        {historyNotice}
        {list}
      </div>
    );

  const active =
    (!stoppedJob(job)
      ? stages.find((stage) => stage.status === 'running' || waitingResources(job, stage))
      : undefined) ??
    stages.find((stage) => stage.status === 'failed') ??
    stages.find((stage) => stage.status === 'running') ??
    stages.find((stage) => stage.status === 'pending');
  const missingResearch =
    !active &&
    job?.include_admet === true &&
    job.admet_only !== true &&
    !stages.some((stage) => stage.name === 'admet') &&
    completeCoreStages(stages);
  const current = missingResearch ? undefined : (active ?? stages.at(-1));
  const currentName = missingResearch ? 'admet' : current?.name;
  const label = !job
    ? '尚未启动'
    : job.history_available !== true
      ? job.history_available === false
        ? '历史阶段不可用'
        : '阶段状态未知'
      : job.status === 'failed' && job.error?.code === 'core_not_accepted'
        ? jobStatusText(job)
        : job.status === 'complete' && !missingResearch
          ? current?.name === 'admet' && current.status === 'empty'
            ? `${stageLabel(current.name, current)} · 未计算`
            : jobStatusText(job)
          : currentName
            ? `${stageLabel(currentName, current)} · ${stageStatusText(job, current, currentName)}`
            : jobStatusText(job);
  const progress = current?.progress;
  const reviewCount = recognitionReviewCount(job);
  return (
    <details className="stage-overview stage-disclosure">
      <summary className="stage-current-line" aria-label="提取阶段详情">
        <output className="stage-current" aria-live="polite" style={{ display: 'inline' }}>
          {label}
          {reviewCount !== null && <span className="stage-progress"> · {reviewCount} 条结构</span>}
          {!completedCoreRejection(job) && progress && progress.total > 0 && (
            <span className="stage-progress"> · {stageProgressText(current)}</span>
          )}
        </output>
      </summary>
      {historyNotice}
      {list}
    </details>
  );
}
