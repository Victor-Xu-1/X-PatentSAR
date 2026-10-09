import { useCallback, useState } from 'react';
import { sarStudyApi } from '../../../api/sarStudyApi';
import type { StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { StudyImage } from './StudyImage';
import { StudyBars } from './StudyBars';
import { GroupPager } from './GroupPager';
import { useSARResource } from '../useSARResource';
import { StudyPolicyNote, hasStrongRule } from './StudyPolicyNote';
export function StudyScaffolds({
  report,
  jobId,
  active,
  onRows,
}: {
  report: StudyReport;
  jobId: string;
  active: boolean;
  onRows: (id: string) => void;
}) {
  const { t } = useTranslation(),
    [page, setPage] = useState(1);
  const load = useCallback(
    (signal: AbortSignal) =>
      sarStudyApi.profile(report.dataset_id, report.dataset_revision, signal),
    [report.dataset_id, report.dataset_revision],
  );
  const profile = useSARResource(
    'sar:core-names:' + report.dataset_id + ':' + report.dataset_revision,
    active,
    load,
  );
  return (
    <div>
      <p className="sar-hint">{t('骨架分组是描述性汇总，不证明严格变化区域关系。')}</p>
      <StudyPolicyNote
        policy={report.policies[0]}
        context={report.contexts.find((context) => context.id === report.policies[0]?.context_id)}
        primary
      />
      <div className="sar-card-grid">
        {report.scaffolds.slice((page - 1) * 12, page * 12).map((scaffold, index) => (
          <article className="sar-study-card" key={scaffold.id}>
            <h3>
              {profile.data?.regions.find((r) => r.id === scaffold.core_region_id)?.name ??
                t('母核 {index}', { index: (page - 1) * 12 + index + 1 })}
            </h3>
            <small>
              {t(
                scaffold.assignment_kind === 'confirmed_core'
                  ? '用户确认核心'
                  : '描述性 Murcko 骨架',
              )}
            </small>
            {scaffold.smiles ? (
              <StudyImage
                jobId={jobId}
                kind="scaffold"
                identifier={scaffold.id}
                label={scaffold.smiles ?? scaffold.id}
                active={active}
              />
            ) : (
              <div className="sar-structure-pending">{t('结构待核对')}</div>
            )}
            {hasStrongRule(report.policies[0]) && (
              <p>
                {t('强活性 {strong}/{total}', {
                  strong: scaffold.strong_count,
                  total: scaffold.molecule_count,
                })}
              </p>
            )}
            {hasStrongRule(report.policies[0]) && (
              <meter
                min={0}
                max={Math.max(1, scaffold.molecule_count)}
                value={scaffold.strong_count}
                aria-label={t('强活性占比')}
              />
            )}
            <StudyBars
              bins={scaffold.bins}
              layout="donut"
              countingContract={report.counting_contract}
              direction={report.policies[0]?.direction}
            />
            <button type="button" onClick={() => onRows(scaffold.id)}>
              {t('查看分子')}
            </button>
          </article>
        ))}
      </div>
      {!report.scaffolds.length && <p>{t('无骨架分组')}</p>}
      <GroupPager page={page} total={report.scaffolds.length} onPage={setPage} />
    </div>
  );
}
