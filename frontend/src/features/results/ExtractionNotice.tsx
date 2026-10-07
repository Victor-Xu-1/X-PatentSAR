import type { Job, Project } from '../../api/types';
import { acceptanceLabels, stageLabels } from '../../model/presentation';
import { completedCoreRejection, observedStages, stoppedJob } from '../../model/extraction';
import { AcceptanceFindings } from './AcceptanceFindings';

export function ExtractionNotice({ project, job }: { project: Project; job: Job | null }) {
  const failed = project.acceptance.state === 'failed' || job?.status === 'failed';
  const trustedStages = observedStages(job);
  const failedStage = trustedStages.find((stage) => stage.status === 'failed');
  const rejectedCore = completedCoreRejection(job);
  const unexecuted = stoppedJob(job)
    ? trustedStages.filter((stage) => stage.status === 'pending')
    : [];
  const errors = project.acceptance.errors.length
    ? project.acceptance.errors
    : job?.error
      ? [job.error.message]
      : [];
  return (
    <div
      className={`acceptance-banner ${failed ? 'failed' : project.acceptance.state}`}
      role={failed ? 'alert' : 'status'}
      aria-label="提取验收与阻塞状态"
    >
      <span>{failed ? '提取未通过验收' : acceptanceLabels[project.acceptance.state]}</span>
      {rejectedCore ? (
        <small>运行已结束，核心验收未通过。</small>
      ) : (
        failedStage && <small>提取在{stageLabels[failedStage.name]}阶段停止。</small>
      )}
      {unexecuted.length > 0 && (
        <small>尚未执行：{unexecuted.map((stage) => stageLabels[stage.name]).join('、')}。</small>
      )}
      <small>
        {project.is_historical
          ? '来源：历史身份产物；旧契约证据不视为当前高置信结果。'
          : failed
            ? '当前表格为待复核候选记录，不是完整结构–活性结果。'
            : '原始提取验收由确定性 QA 决定；补充记录与人工修正不改变验收。'}
      </small>
      <AcceptanceFindings errors={errors} open={failed} />
    </div>
  );
}
