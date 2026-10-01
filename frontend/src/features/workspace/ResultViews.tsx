import type { ComponentProps } from 'react';
import type { Health } from '../../api/types';
import type { ResultTab } from '../../model/route';
import { ResultsPane } from '../results/ResultsPane';
import { AdmetPanel } from '../analysis/AdmetPanel';
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
  return (
    <section className="panel results-pane" aria-label="结构与活性提取结果">
      {tab !== 'results' && (
        <header className="analysis-view-heading">
          <button type="button" onClick={() => onTab('results')}>
            返回结构列表
          </button>
          <span>{tab === 'admet' ? '分子分析' : '证据摘要'}</span>
        </header>
      )}
      <section
        className={`result-view result-view-${tab}`}
        aria-label={
          tab === 'results' ? '结构与活性数据' : tab === 'admet' ? '分子分析' : '项目证据摘要'
        }
      >
        {tab === 'results' ? (
          <ResultsPane {...resultProps} />
        ) : tab === 'admet' ? (
          <AdmetPanel available={capabilities?.admet ?? null} />
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
