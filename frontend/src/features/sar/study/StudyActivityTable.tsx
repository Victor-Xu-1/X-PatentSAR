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
  return (
    <div>
      <StudyTableControls
        report={report}
        filter={filter}
        onFilter={onFilter}
        columns={columns}
        hidden={hidden}
        onHidden={setHidden}
        sort={sort}
        onSort={setSort}
      />
      {rows.loading && <Loading />}
      {rows.error && <SARFailure error={rows.error} onRetry={rows.reload} />}
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
