import type { Job, Project } from '../../api/types';
import { acceptanceLabels, stageLabels } from '../../model/presentation';
import { observedStages, stoppedJob } from '../../model/extraction';

export function ExtractionNotice({ project, job }: { project: Project; job: Job | null }) {
  const failed = project.acceptance.state === 'failed' || job?.status === 'failed';
  const trustedStages = observedStages(job);
  const failedStage = trustedStages.find((stage) => stage.status === 'failed');
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
      {failedStage && <small>提取在{stageLabels[failedStage.name]}阶段停止。</small>}
      {unexecuted.length > 0 && (
        <small>尚未执行：{unexecuted.map((stage) => stageLabels[stage.name]).join('、')}。</small>
      )}
      <small>
        {project.is_historical
          ? '来源：历史身份产物；旧契约证据不视为当前高置信结果。'
          : failed
            ? '当前表格为待复核候选记录，不是完整结构–活性结果。'
            : '正式验收仅由确定性 QA 决定，人工注记不改变验收。'}
      </small>
      {errors.length > 0 && (
        <details open={failed}>
          <summary>查看核心验收问题（{errors.length}）</summary>
          <ul>
            {errors.map((error, index) => (
              <li key={index}>{error}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
