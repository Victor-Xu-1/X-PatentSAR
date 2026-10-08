import { useTranslation } from '../../i18n';
import type { EvidenceSummary } from '../../api/analysisTypes';

export function EvidenceActivityTable({
  activities,
}: {
  activities: EvidenceSummary['activities'];
}) {
  const { t } = useTranslation();
  return (
    <section className="evidence-activities" aria-label={t('按实验上下文分列的活性证据')}>
      <h3>{t('活性证据')}</h3>
      {activities.length ? (
        <div className="analysis-table-scroll">
          <table className="analysis-table">
            <caption className="sr-only">
              {t('按指标、单位和靶点分别统计；删失与范围值不作为精确极值')}
            </caption>
            <thead>
              <tr>
                {[
                  t('指标'),
                  t('单位'),
                  t('靶点'),
                  t('行数'),
                  t('数值行'),
                  t('最小'),
                  t('最大'),
                  t('删失行'),
                ].map((label) => (
                  <th key={label}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {activities.map((activity, index) => (
                <tr key={index}>
                  <th scope="row">{activity.name}</th>
                  <td>{activity.unit ?? t('未提供')}</td>
                  <td>{activity.target ?? t('未提供')}</td>
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
        <p className="muted">{t('此项目没有可汇总的活性记录。')}</p>
      )}
    </section>
  );
}
