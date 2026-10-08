import { useTranslation } from '../../i18n';
import type { ComponentProps } from 'react';
import type { Health } from '../../api/types';
import type { ResultTab } from '../../model/route';
import { ResultsPane } from '../results/ResultsPane';
import { EvidencePanel } from '../analysis/EvidencePanel';

export function ResultViews({
  tab,
  onTab,
  capabilities,
  resultProps,
  onSource,
}: {
  tab: ResultTab;
  onTab: (tab: ResultTab) => void;
  capabilities: Health['capabilities'] | null;
  resultProps: ComponentProps<typeof ResultsPane>;
  onSource: (page: number) => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="panel results-pane" aria-label={t('结构与活性提取结果')}>
      {tab !== 'results' && (
        <header className="analysis-view-heading">
          <button type="button" onClick={() => onTab('results')}>
            {t('返回结构列表')}
          </button>
          <span>{t('证据摘要')}</span>
        </header>
      )}
      <section
        className={`result-view result-view-${tab}`}
        aria-label={tab === 'results' ? t('结构与活性数据') : t('项目证据摘要')}
      >
        {tab === 'results' ? (
          <ResultsPane {...resultProps} />
        ) : (
          <EvidencePanel
            project={resultProps.project}
            available={capabilities?.summary ?? null}
            onSource={onSource}
          />
        )}
      </section>
    </section>
  );
}
