import { useTranslation } from '../../i18n';
import type { Job, StageName } from '../../api/types';
import {
  pageProgressStage,
  reviewedCoreStage,
  stageLabel,
  stageStatusText,
} from '../../model/extraction';
import { jobStageProgressText } from '../../model/jobPresentation';

export function StageObservation({
  job,
  stage,
  name,
}: {
  job: Job;
  stage: Job['stages'][number] | undefined;
  name: StageName;
}) {
  const { t } = useTranslation();
  const progress = stage?.progress;
  const resourceWait = stage?.resource_wait;
  const label = t(stageLabel(name, stage));
  const state = t(stageStatusText(job, stage, name));
  const work = jobStageProgressText(stage);
  const finding = t(name === 'smiles' && reviewedCoreStage(job, stage) ? '待复核' : '失败');
  const countText =
    work ?? (stage?.count == null ? null : t('数量 {count}', { count: stage.count }));
  const analysisNote =
    name === 'admet'
      ? t(' · {context}；MW、LogP、TPSA、HBD、HBA 计算，LogS 为 ADMET 预测', {
          context: t(job.admet_only ? '补齐已证实来源的结构与指标' : '核心校验后执行'),
        })
      : '';
  return (
    <details className="stage-observation" name={'stage-observations-' + job.id}>
      <summary
        title={[
          t('{label}：{state}', { label, state }),
          countText === null ? '' : ' · ' + countText,
          analysisNote,
        ].join('')}
      >
        <strong>{label}</strong>
        <small>
          <span>{state}</span>
          {!progress &&
            stage?.count != null &&
            ' · ' +
              (stage.status === 'failed' ? t('数量 {count}', { count: stage.count }) : stage.count)}
          {work && <span className="stage-progress"> · {work}</span>}
        </small>
      </summary>
      <div className="stage-observation-detail">
        {stage?.repair && (
          <p>
            {t('来源区域 {regions} · 待修复 {unresolved}', {
              regions: stage.repair.regions,
              unresolved: stage.repair.unresolved,
            })}
          </p>
        )}
        {resourceWait && (
          <>
            <p>
              {t('所需内存 {required} MB · 可用 {available} MB', {
                required: resourceWait.required_mb,
                available: resourceWait.available_mb,
              })}
            </p>
            <p>{t('已等待 {seconds} 秒', { seconds: resourceWait.waited_seconds })}</p>
          </>
        )}
        {!progress ? (
          <p>{t('进度未提供')}</p>
        ) : (
          <>
            <p>
              {pageProgressStage(name)
                ? t('复用 {pages} 页', { pages: progress.cache_hits })
                : t('缓存命中 {hits} · {finding} {failures}', {
                    hits: progress.cache_hits,
                    finding,
                    failures: progress.failures,
                  })}
            </p>
            {(!pageProgressStage(name) ||
              progress.device !== null ||
              progress.peak_rss_mb !== null) && (
              <p>
                {progress.device === null ? t('执行设备未知') : progress.device.toUpperCase()}
                {' · '}
                {progress.peak_rss_mb === null
                  ? t('峰值 RSS 未提供')
                  : t('峰值 RSS {rss} MB', { rss: progress.peak_rss_mb })}
              </p>
            )}
          </>
        )}
        {stage?.reused_checkpoint == null && <p>{t('检查点复用未知')}</p>}
        {stage?.reused_checkpoint === true && <p>{t('复用检查点')}</p>}
        {progress && stage?.count != null && (
          <p>{t('阶段记录数量 {count}', { count: stage.count })}</p>
        )}
        {name === 'admet' && stage?.skipped != null && stage.skipped > 0 && (
          <p>{t('未计算 {count}（缺少有效SMILES）', { count: stage.skipped })}</p>
        )}
        {stage?.reused_checkpoint === false && <p>{t('本次执行，未复用检查点')}</p>}
        <p className="muted">{t('只展示服务端观察，不推算准确率、百分比或剩余时间。')}</p>
      </div>
    </details>
  );
}
