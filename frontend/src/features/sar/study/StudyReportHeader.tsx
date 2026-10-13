import type { JobState } from '../../../api/sarTypes';
import { useTranslation } from '../../../i18n';
import { jobLabels } from '../presentation';

export function StudyReportHeader({
  title,
  status,
  historical,
  research,
  disabled,
  onRefresh,
  onDetails,
  coverage,
  onNewAnalysis,
  newAnalysisDisabled = true,
  hasDraft = false,
}: {
  title: string | null;
  status: JobState | null;
  historical: boolean;
  research: boolean;
  disabled: boolean;
  onRefresh: () => void;
  onDetails: (() => void) | null;
  coverage?: { automatic: boolean; references: number; regions: number } | null;
  onNewAnalysis?: (() => void) | undefined;
  newAnalysisDisabled?: boolean | undefined;
  hasDraft?: boolean | undefined;
}) {
  const { t } = useTranslation();
  return (
    <header className="sar-study-header">
      <div className="sar-study-heading">
        <h2>{title ?? t('研究报告')}</h2>
        <div className="sar-study-state" aria-live="polite">
          {status && <strong data-state={status}>{t(jobLabels[status])}</strong>}
          {historical && (
            <output
              className="sar-source-status is-review"
              title={t('结果已过期，仅供历史核对；禁止续跑或作为当前结论。')}
            >
              {t('历史研究')}
            </output>
          )}
          {research && (
            <span className="sar-research-label" title={t('研究候选 · 非实验验收')}>
              {t('研究预览')}
            </span>
          )}
          {coverage && (
            <span className="sar-study-coverage">
              {coverage.automatic
                ? t(
                    coverage.references === 1 ? '全库发现 · 1 个参考' : '全库发现 · {count} 个参考',
                    { count: coverage.references },
                  )
                : coverage.regions
                  ? t(
                      coverage.references === 1
                        ? '手工区域 · 1 个参考'
                        : '手工区域 · {count} 个参考',
                      { count: coverage.references },
                    )
                  : t('未选择变化区域')}
            </span>
          )}
        </div>
      </div>
      <div className="sar-study-header-actions">
        {onNewAnalysis && (
          <button type="button" disabled={disabled || newAnalysisDisabled} onClick={onNewAnalysis}>
            {t(hasDraft ? '继续设置' : '新分析')}
          </button>
        )}
        <button type="button" disabled={disabled} onClick={onRefresh}>
          {t('刷新')}
        </button>
        {onDetails && (
          <button type="button" onClick={onDetails}>
            {t('研究详情')}
          </button>
        )}
      </div>
    </header>
  );
}
