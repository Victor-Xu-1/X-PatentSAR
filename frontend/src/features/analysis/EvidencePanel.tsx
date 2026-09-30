import { useCallback } from 'react';
import { api } from '../../api';
import type { Project } from '../../api/types';
import { useResource } from '../../hooks/useResource';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
import { acceptanceLabels, dateText } from '../../model/presentation';
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
        <h2>确定性证据统计 · 同项目摘要</h2>
        <button type="button" onClick={resource.reload} disabled={!id || resource.loading}>
          刷新证据摘要
        </button>
      </header>
      <p className="analysis-notice">
        仅聚合原始字段与来源；不是 LLM 摘要，不推断机制或疗效，不合并不同单位/靶点，不改变正式验收。
      </p>
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
          <p className="analysis-provenance">
            {acceptanceLabels[summary.acceptance.state]} · {dateText(summary.generated_at)}
          </p>
          <dl className="evidence-counts">
            {Object.entries({
              结构: summary.counts.structures,
              活性行: summary.counts.activity_rows,
              化合物: summary.counts.compounds,
              已有SMILES: summary.counts.smiles,
              来源已定位: summary.counts.source_located,
              待复核: summary.counts.needs_review,
            }).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {summary.acceptance.errors.length > 0 && (
            <ul className="analysis-warnings">
              {summary.acceptance.errors.map((error, i) => (
                <li key={i}>{error}</li>
              ))}
            </ul>
          )}
          <h3>活性证据（按指标、单位、靶点分别统计）</h3>
          {summary.activities.length ? (
            <div className="analysis-table-scroll">
              <table className="analysis-table">
                <caption className="sr-only">真实活性统计；删失与范围值不作为精确极值</caption>
                <thead>
                  <tr>
                    <th>指标</th>
                    <th>单位</th>
                    <th>靶点</th>
                    <th>行数</th>
                    <th>数值行</th>
                    <th>最小</th>
                    <th>最大</th>
                    <th>删失行</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.activities.map((activity, i) => (
                    <tr key={i}>
                      <th scope="row">{activity.name}</th>
                      <td>{activity.unit ?? '未提供'}</td>
                      <td>{activity.target ?? '未提供'}</td>
                      <td>{activity.rows}</td>
                      <td>{activity.numeric_rows}</td>
                      <td>{activity.min ?? '—'}</td>
                      <td>{activity.max ?? '—'}</td>
                      <td>{activity.censored_rows}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">此项目没有可汇总的活性记录。</p>
          )}
          <div className="evidence-targets">
            <h3>靶点记录</h3>
            {summary.targets.map((target, i) => (
              <span key={i}>
                {target.name} · {target.rows} 行
              </span>
            ))}
          </div>
          <div className="evidence-sources">
            <h3>原始来源页</h3>
            {summary.source_pages.length ? (
              summary.source_pages.map((page) => (
                <button
                  type="button"
                  key={page}
                  aria-label={`查看来源第 ${page} 页`}
                  onClick={() => onSource(page)}
                >
                  第 {page} 页
                </button>
              ))
            ) : (
              <p className="muted">来源页未提供</p>
            )}
          </div>
          {summary.limitations.length > 0 && (
            <div>
              <h3>证据局限</h3>
              <ul>
                {summary.limitations.map((limit, i) => (
                  <li key={i}>{limit}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
