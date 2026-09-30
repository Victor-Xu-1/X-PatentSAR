import { useState } from 'react';
import { api } from '../../api';
import type { AdmetResult } from '../../api/analysisTypes';
import { AnalysisFeedback } from './AnalysisFeedback';
import { parseSmiles } from '../../model/analysis';
import { AnalysisNotice } from './AnalysisNotice';
import { useAnalysis } from './useAnalysis';
import { AdmetResults } from './AdmetResults';

export function AdmetPanel({
  initialSmiles = '',
  available,
  blocked = false,
  onBusy,
}: {
  initialSmiles?: string;
  available?: boolean | null;
  blocked?: boolean;
  onBusy?: (busy: boolean) => void;
}) {
  const [input, setInput] = useState(initialSmiles);
  const [previousSeed, setPreviousSeed] = useState(initialSmiles);
  if (previousSeed !== initialSmiles) {
    setPreviousSeed(initialSmiles);
    setInput(initialSmiles);
  }
  const analysis = useAnalysis<AdmetResult>(onBusy);
  return (
    <section className="analysis-panel" aria-label="输入分子进行本地 ADMET 分析">
      <h2>分子分析 · ADMET</h2>
      <AnalysisNotice available={available ?? null} />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void analysis.run((signal) => api.admet(parseSmiles(input), signal));
        }}
        aria-busy={analysis.busy}
      >
        <label className="form-field">
          SMILES（每行一个，最多 50 个）
          <textarea
            rows={4}
            maxLength={205_000}
            spellCheck={false}
            value={input}
            disabled={analysis.busy || blocked}
            onChange={(e) => setInput(e.target.value)}
          />
        </label>
        <p className="muted">
          没有提取 SMILES 也可直接输入；或点击结果表中的真实结构裁图，先用 DECIMER + RDKit QC 识别。
        </p>
        <button
          type="submit"
          className="primary"
          disabled={analysis.busy || analysis.uncertain || blocked}
        >
          运行本地 ADMET
        </button>
      </form>
      <AnalysisFeedback {...analysis} pendingLabel="正在执行本地分子分析…" />
      {analysis.result && <AdmetResults result={analysis.result} />}
    </section>
  );
}
