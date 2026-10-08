import { useCallback, useState } from 'react';
import { sarStudyApi } from '../../../api/sarStudyApi';
import type { StudyFilter, StudyReport, StudyRow } from '../../../api/sarStudyTypes';
import { useDebounced } from '../../../hooks/useDebounced';
import { useTranslation } from '../../../i18n';
import { Loading } from '../../../components/Feedback';
import { SARFailure } from '../SARFailure';
import { useSARResource } from '../useSARResource';
import { PageControls } from '../PageControls';
import { studyColumns, StudyRowTable } from './StudyRowTable';
import { selectedContexts } from './tablePresentation';
import type { PageSort } from './tablePresentation';
import { StudyTableControls } from './StudyTableControls';
export function StudyActivityTable({
  jobId,
  report,
  active,
  filter,
  onFilter,
  onSource,
}: {
  jobId: string;
  report: StudyReport;
  active: boolean;
  filter: StudyFilter;
  onFilter: (filter: StudyFilter) => void;
  onSource: (id: string, row: StudyRow) => void;
}) {
  const { t } = useTranslation(),
    search = useDebounced(filter.query, 250);
  const [hidden, setHidden] = useState<string[]>([]),
    [sort, setSort] = useState<PageSort>({ column: '', direction: 'asc' });
  const columns = studyColumns(selectedContexts(report), t);
  const key = JSON.stringify({ ...filter, query: search, sort });
  const [paging, setPaging] = useState({ key, page: 1 });
  if (paging.key !== key) setPaging({ key, page: 1 });
  const page = paging.key === key ? paging.page : 1;
  const load = useCallback(
    (signal: AbortSignal) =>
      sarStudyApi.rows(jobId, report.dataset_id, page, { ...filter, query: search }, signal, sort),
    [jobId, report.dataset_id, page, filter, search, sort],
  );
  const rows = useSARResource('sar:study-rows:' + jobId + ':' + page + ':' + key, active, load);
  function change(patch: Partial<StudyFilter>) {
    onFilter({ ...filter, ...patch });
  }
  return (
    <div>
      <div className="sar-study-filters">
        <label>
          {t('搜索编号或 SMILES')}
          <input
            type="search"
            maxLength={200}
            value={filter.query}
            onChange={(e) => change({ query: e.target.value })}
          />
        </label>
        <label>
          {t('研究行范围')}
          <select
            value={filter.scope}
            onChange={(e) => change({ scope: e.target.value as StudyFilter['scope'] })}
          >
            <option value="all">{t('全部研究行')}</option>
            <option value="strong">{t('强活性')}</option>
            <option value="leads">{t('研究先导候选')}</option>
          </select>
        </label>
        <label>
          {t('研究骨架')}
          <select
            value={filter.scaffold_id}
            onChange={(e) => change({ scaffold_id: e.target.value })}
          >
            <option value="">{t('全部状态')}</option>
            {report.scaffolds.map((s, i) => (
              <option key={s.id} value={s.id}>
                {t('母核 {index}', { index: i + 1 })} · {s.molecule_count}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t('变化区域')}
          <select
            value={filter.region_id}
            onChange={(e) => change({ region_id: e.target.value, fragment_id: '' })}
          >
            <option value="">{t('全部状态')}</option>
            {report.regions.map((r, i) => (
              <option key={r.region.id} value={r.region.id}>
                {r.region.name ?? 'R' + (i + 1)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t('研究片段')}
          <select
            value={filter.fragment_id}
            onChange={(e) => change({ fragment_id: e.target.value })}
            disabled={!filter.region_id}
          >
            <option value="">{t('全部状态')}</option>
            {report.regions
              .find((r) => r.region.id === filter.region_id)
              ?.fragments.map((f, i) => (
                <option key={f.id} value={f.id}>
                  {t('片段 {index}', { index: i + 1 })} · {f.molecule_count}
                </option>
              ))}
          </select>
        </label>
      </div>
      <p className="sar-hint">
        {t('按原始编号自然顺序；筛选和分页由服务器执行，导出保留全部报告。')}
      </p>
      {rows.loading && <Loading />}
      {rows.error && <SARFailure error={rows.error} onRetry={rows.reload} />}
      <StudyTableControls
        columns={columns}
        hidden={hidden}
        onHidden={setHidden}
        sort={sort}
        onSort={setSort}
      />
      {rows.data && (
        <StudyRowTable
          jobId={jobId}
          rows={rows.data.items}
          columns={columns}
          hidden={hidden}
          active={active && rows.validated}
          onSource={onSource}
        />
      )}
      {rows.data?.items.length === 0 && <p>{t('没有匹配行')}</p>}
      {rows.data && (
        <PageControls
          page={page}
          total={rows.data.total}
          onPage={(next) => setPaging({ key, page: next })}
          disabled={!rows.validated || search !== filter.query}
        />
      )}
    </div>
  );
}
