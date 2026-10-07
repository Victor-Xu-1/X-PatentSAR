import { useCallback } from 'react';
import { api } from '../../api';
import type { Project } from '../../api/types';
import { useResource } from '../../hooks/useResource';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
import { acceptanceLabels, dateText } from '../../model/presentation';
import { EvidenceActivityTable } from './EvidenceActivityTable';
import { EvidenceDetails } from './EvidenceDetails';

export function EvidencePanel({
  project,
  available,
  onSource,
}: {
  project: Project | null;
  available?: boolean | null;
  onSource: (page: number) => void;
}) {
  const id = project?.id;
  const load = useCallback((signal: AbortSignal) => api.evidenceSummary(id ?? '', signal), [id]);
  const resource = useResource(id ? `evidence:${id}` : null, load);
  const summary = resource.data;
  return (
    <section className="analysis-panel evidence-panel" aria-label="同项目确定性证据摘要">
      <header className="evidence-header">
        <div>
          <h2>证据摘要</h2>
          <p className="analysis-provenance">确定性证据统计 · 不改变原始验收</p>
        </div>
        <button type="button" onClick={resource.reload} disabled={!id || resource.loading}>
          刷新证据摘要
        </button>
      </header>
      {available === false && (
        <p className="info-banner">
          服务报告摘要能力当前不可用，以下请求会保留真实错误。<a href="#/settings">检查环境管理</a>
        </p>
      )}
      {!project ? (
        <Empty
          title="请选择项目以读取证据摘要"
          description="从项目列表打开已有结果；不会跨项目混合证据。"
        />
      ) : resource.error ? (
        <ErrorNotice error={resource.error} onRetry={resource.reload} />
      ) : resource.loading && !summary ? (
        <Loading label="正在聚合同项目真实证据…" />
      ) : summary ? (
        <>
          <div className="evidence-state">
            <span className={`badge ${summary.acceptance.state}`}>
              {acceptanceLabels[summary.acceptance.state]}
            </span>
            <time dateTime={summary.generated_at}>{dateText(summary.generated_at)}</time>
          </div>
          <dl className="evidence-counts">
            {Object.entries({
              结构观察: summary.counts.structures,
              活性记录: summary.counts.activity_rows,
              表格记录: summary.counts.compounds,
              '已有 SMILES': summary.counts.smiles,
              来源已定位: summary.counts.source_located,
              待核对记录: summary.counts.needs_review,
            }).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <EvidenceDetails
            errors={summary.acceptance.errors}
            pages={summary.source_pages}
            limitations={summary.limitations}
            onSource={onSource}
          />
          <EvidenceActivityTable activities={summary.activities} />
          <section className="evidence-targets" aria-label="靶点记录">
            <h3>靶点记录</h3>
            {summary.targets.map((target, index) => (
              <span key={index}>
                {target.name} · {target.rows} 行
              </span>
            ))}
          </section>
        </>
      ) : null}
    </section>
  );
}
