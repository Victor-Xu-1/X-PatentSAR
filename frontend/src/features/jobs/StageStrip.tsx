import { useTranslation } from '../../i18n';
import { useEffect, useRef } from 'react';
import { ChevronDown, CircleAlert } from 'lucide-react';
import type { Job } from '../../api/types';
import { jobStatusText } from '../../model/presentation';
import { jobStageProgressText } from '../../model/jobPresentation';
import {
  completeCoreStages,
  completedCoreRejection,
  observedStages,
  recognitionReviewCount,
  stageLabel,
  stageStatusText,
  stoppedJob,
  waitingResources,
  workflowStageNames,
} from '../../model/extraction';
import { StageList } from './StageList';
import { WorkflowGroups } from './WorkflowGroups';

export function StageStrip({
  job,
  compact = false,
  verified = true,
}: {
  job: Job | null;
  compact?: boolean;
  verified?: boolean;
}) {
  const { t } = useTranslation();
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
          ? t('历史阶段不可用：本次任务的阶段记录无法可靠读取。')
          : t('历史阶段可用性未知')}
      </output>
    ) : null;
  const list =
    !verified && !job ? (
      <output>{t('阶段状态未知')}</output>
    ) : (
      <StageList job={job} stages={stages} names={names} />
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
  const label = !verified
    ? t('阶段状态未知')
    : !job
      ? t('尚未启动')
      : job.history_available !== true
        ? job.history_available === false
          ? t('历史阶段不可用')
          : t('阶段状态未知')
        : job.status === 'failed' && job.error?.code === 'core_not_accepted'
          ? jobStatusText(job)
          : job.status === 'complete' && !missingResearch
            ? current?.name === 'admet' && current.status === 'empty'
              ? t('{label} · 未计算', { label: t(stageLabel(current.name, current)) })
              : jobStatusText(job)
            : currentName
              ? `${t(stageLabel(currentName, current))} · ${t(stageStatusText(job, current, currentName))}`
              : jobStatusText(job);
  const progress = current?.progress;
  const sourceWork =
    verified &&
    job?.status === 'running' &&
    current?.status === 'running' &&
    current.name === 'bind' &&
    progress?.source_phase &&
    !waitingResources(job, current)
      ? jobStageProgressText(current)
      : null;
  const known = verified && (!job || job.history_available === true);
  const reviewCount = known ? recognitionReviewCount(job) : null;
  const progressText =
    verified && !completedCoreRejection(job) && !sourceWork && progress && progress.total > 0
      ? jobStageProgressText(current)
      : null;
  const stoppedPrefix =
    verified && job && ['cancelled', 'interrupted'].includes(job.status)
      ? `${jobStatusText(job)} · `
      : '';
  const currentText = sourceWork
    ? `${t(stageStatusText(job, current, currentName!))} · ${sourceWork}`
    : label;
  const summaryText = `${stoppedPrefix}${currentText}${reviewCount !== null ? ` · ${t('{count} 条结构', { count: reviewCount })}` : ''}${progressText ? ` · ${progressText}` : ''}`;
  return (
    <details className="stage-overview stage-disclosure" ref={disclosure}>
      <summary className="stage-current-line" aria-label={t('提取阶段详情')}>
        <WorkflowGroups job={job} />
        <span
          className={`stage-current ${!known ? 'is-unknown' : completedCoreRejection(job) ? 'is-review' : `is-${job?.status ?? 'idle'}`}`}
          aria-live="polite"
          aria-atomic="true"
          title={sourceWork ? `${label} · ${sourceWork}` : summaryText}
        >
          {known && job?.status === 'failed' && (
            <CircleAlert size={16} className="stage-state-icon" aria-hidden="true" />
          )}
          <span className="stage-current-text">{summaryText}</span>
        </span>
        <ChevronDown size={14} className="stage-disclosure-chevron" aria-hidden="true" />
      </summary>
      <div className="stage-detail-surface">
        <h2>{t('任务流程')}</h2>
        {historyNotice}
        {list}
      </div>
    </details>
  );
}
