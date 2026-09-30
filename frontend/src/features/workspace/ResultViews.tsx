import type { ComponentProps } from 'react';
import { RefreshCw } from 'lucide-react';
import type { Health } from '../../api/types';
import type { ResultTab } from '../../model/route';
import { Tabs } from '../../components/Tabs';
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
      <header className="result-tabs">
        <Tabs
          label="结果与独立复核分析"
          value={tab}
          onChange={onTab}
          tabs={[
            { value: 'results', label: '结构–活性结果' },
            { value: 'admet', label: '分子分析 · ADMET' },
            { value: 'summary', label: '证据摘要' },
          ]}
        />
        {tab === 'results' && (
          <button
            type="button"
            className="icon-button"
            aria-label="刷新真实提取结果"
            onClick={resultProps.resource.reload}
            disabled={!resultProps.project || resultProps.resource.loading}
          >
            <RefreshCw size={14} />
          </button>
        )}
      </header>
      <div
        className={`result-view result-view-${tab}`}
        role="tabpanel"
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
      </div>
    </section>
  );
}
