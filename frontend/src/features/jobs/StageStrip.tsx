import { useEffect, useRef } from 'react';
import { ChevronDown } from 'lucide-react';
import type { Job } from '../../api/types';
import { jobStatusText } from '../../model/presentation';
import {
  completeCoreStages,
  completedCoreRejection,
  observedStages,
  recognitionReviewCount,
  stageLabel,
  stageProgressText,
  stageStatusText,
  stoppedJob,
  waitingResources,
  workflowStageNames,
} from '../../model/extraction';
import { StageList } from './StageList';
import { WorkflowGroups } from './WorkflowGroups';

export function StageStrip({ job, compact = false }: { job: Job | null; compact?: boolean }) {
  const disclosure = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (!compact) return;
    const outside = (event: PointerEvent) => {
      const current = disclosure.current;
      if (current?.open && event.target instanceof Node && !current.contains(event.target))
        current.open = false;
    };
    const escape = (event: KeyboardEvent) => {
      const current = disclosure.current;
      if (event.key === 'Escape' && current?.open && !document.querySelector('dialog[open]')) {
        event.preventDefault();
        current.open = false;
        current.querySelector('summary')?.focus();
      }
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape);
    };
  }, [compact]);
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
  const list = <StageList job={job} stages={stages} names={names} />;
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
    <details className="stage-overview stage-disclosure" ref={disclosure}>
      <summary className="stage-current-line" aria-label="提取阶段详情">
        <WorkflowGroups job={job} />
        <output
          className={`stage-current ${completedCoreRejection(job) ? 'is-review' : `is-${job?.status ?? 'idle'}`}`}
          aria-live="polite"
        >
          {job && ['cancelled', 'interrupted'].includes(job.status) && `${jobStatusText(job)} · `}
          {label}
          {reviewCount !== null && <span className="stage-progress"> · {reviewCount} 条结构</span>}
          {!completedCoreRejection(job) && progress && progress.total > 0 && (
            <span className="stage-progress"> · {stageProgressText(current)}</span>
          )}
        </output>
        <ChevronDown size={14} className="stage-disclosure-chevron" aria-hidden="true" />
      </summary>
      <div className="stage-detail-surface">
        <h2>任务流程</h2>
        {historyNotice}
        {list}
      </div>
    </details>
  );
}
