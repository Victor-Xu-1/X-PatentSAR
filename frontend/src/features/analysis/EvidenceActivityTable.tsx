import type { EvidenceSummary } from '../../api/analysisTypes';

export function EvidenceActivityTable({
  activities,
}: {
  activities: EvidenceSummary['activities'];
}) {
  return (
    <section className="evidence-activities" aria-label="按实验上下文分列的活性证据">
      <h3>活性证据</h3>
      {activities.length ? (
        <div className="analysis-table-scroll">
          <table className="analysis-table">
            <caption className="sr-only">
              按指标、单位和靶点分别统计；删失与范围值不作为精确极值
            </caption>
            <thead>
              <tr>
                {['指标', '单位', '靶点', '行数', '数值行', '最小', '最大', '删失行'].map(
                  (label) => (
                    <th key={label}>{label}</th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {activities.map((activity, index) => (
                <tr key={index}>
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
    </section>
  );
}
