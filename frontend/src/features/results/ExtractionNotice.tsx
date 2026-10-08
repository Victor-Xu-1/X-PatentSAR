import { useTranslation } from '../../i18n';
import type { Job, Project } from '../../api/types';
import { acceptanceLabels, stageLabels } from '../../model/presentation';
import { completedCoreRejection, observedStages, stoppedJob } from '../../model/extraction';
import { AcceptanceFindings } from './AcceptanceFindings';

export function ExtractionNotice({ project, job }: { project: Project; job: Job | null }) {
  const { locale, t } = useTranslation();
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
      aria-label={t('提取验收与阻塞状态')}
    >
      <span>{failed ? t('提取未通过验收') : t(acceptanceLabels[project.acceptance.state])}</span>
      {rejectedCore ? (
        <small>{t('运行已结束，核心验收未通过。')}</small>
      ) : (
        failedStage && (
          <small>{t('提取在{stage}阶段停止。', { stage: t(stageLabels[failedStage.name]) })}</small>
        )
      )}
      {unexecuted.length > 0 && (
        <small>
          {t('尚未执行：{stages}。', {
            stages: unexecuted
              .map((stage) => t(stageLabels[stage.name]))
              .join(locale === 'en' ? ', ' : '、'),
          })}
        </small>
      )}
      <small>
        {project.is_historical
          ? t('来源：历史身份产物；旧契约证据不视为当前高置信结果。')
          : failed
            ? t('当前表格为待复核候选记录，不是完整结构–活性结果。')
            : t('原始提取验收由确定性 QA 决定；补充记录与人工修正不改变验收。')}
      </small>
      <AcceptanceFindings errors={errors} open={failed} />
    </div>
  );
}
