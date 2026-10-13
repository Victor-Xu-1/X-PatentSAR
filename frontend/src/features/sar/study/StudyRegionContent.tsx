import { useCallback } from 'react';
import type { CatalogRegion, CatalogReport } from '../../../api/sarCatalogTypes';
import { sarStudyApi } from '../../../api/sarStudyApi';
import { verifyRegionDetail } from '../../../api/sarStudyIntegrity';
import { ContractError } from '../../../api/validation';
import { Loading } from '../../../components/Feedback';
import { SARFailure } from '../SARFailure';
import { useSARResource } from '../useSARResource';
import { StudyRegionGroup } from './StudyRegionGroup';

export function StudyRegionContent(props: {
  summary: CatalogRegion;
  index: number;
  jobId: string;
  active: boolean;
  strongest: boolean;
  report: CatalogReport;
  onRows: (region: string, fragment: string) => void;
  onSource: (id: string) => void;
}) {
  const { report, summary, jobId, active } = props;
  const regionId = summary.region.id;
  const load = useCallback(
    async (signal: AbortSignal) => {
      const value = await sarStudyApi.region(jobId, report.dataset_id, regionId, signal);
      if (
        value.job.input_sha256 !== report.input_sha256 ||
        value.activity_basis.retained_records !== report.molecule_count
      )
        throw new ContractError('$.region_source');
      verifyRegionDetail(report, value.region);
      return value.region;
    },
    [jobId, report, regionId],
  );
  const resource = useSARResource(
    JSON.stringify(['sar:region-detail', jobId, report.input_sha256, regionId]),
    active,
    load,
  );
  return (
    <>
      {resource.loading && <Loading />}
      {resource.error && <SARFailure error={resource.error} onRetry={resource.reload} />}
      {resource.validated && resource.data && (
        <StudyRegionGroup {...props} summary={resource.data} />
      )}
    </>
  );
}
