import type { CatalogRegion, CatalogReport } from '../../../api/sarCatalogTypes';
import { useCallback, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { sarStudyApi } from '../../../api/sarStudyApi';
import type { StudyRow } from '../../../api/sarStudyTypes';
import { ContractError } from '../../../api/validation';
import { Loading } from '../../../components/Feedback';
import { useScrollFocus } from '../../../components/useScrollFocus';
import { useTranslation } from '../../../i18n';
import { SARFailure } from '../SARFailure';
import { useSARResource } from '../useSARResource';
import { networkRowSites } from './networkSites';
import { MatrixHead } from './MatrixHead';
import { MatrixValues } from './MatrixValues';
import { MatrixPredictions } from './MatrixPredictions';
import { matrixReadings } from './matrixReadings';
import { moveMatrix } from './matrixScrolling';
import { useMediaQuery } from '../../../hooks/useMediaQuery';
import { MatrixPairControls } from './MatrixPairControls';

export function NetworkMatrix({
  rows,
  report,
  sites,
  siteOrder,
  referenceId,
  jobId,
  active,
  onCompare,
  onSource,
}: {
  rows: StudyRow[];
  report: CatalogReport;
  sites: CatalogRegion[];
  siteOrder: ReadonlyMap<string, number>;
  referenceId: string;
  jobId: string;
  active: boolean;
  onCompare: (site: CatalogRegion, molecule: string, button: HTMLButtonElement) => void;
  onSource: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const paired = useMediaQuery('(max-width: 700px)');
  const [candidate, setCandidate] = useState('');
  const choices = rows.map((row) => networkRowSites(sites, row.molecule_id));
  const selections = rows.map((row, index) => ({
    molecule_id: row.molecule_id,
    region_id:
      choices[index]?.find((item) => item.region.id === chosen[row.molecule_id])?.region.id ??
      choices[index]?.[0]?.region.id ??
      '',
  }));
  const identity = JSON.stringify(selections);
  const load = useCallback(
    (signal: AbortSignal) =>
      sarStudyApi.matrix(jobId, report.dataset_id, referenceId, JSON.parse(identity), signal),
    [jobId, report.dataset_id, referenceId, identity],
  );
  const resource = useSARResource(
    'sar:matrix:' + jobId + ':' + referenceId + ':' + identity,
    active,
    load,
  );
  const data = resource.validated ? resource.data : null;
  const candidateIndex = Math.max(
    0,
    data?.previews.findIndex((item) => item.candidate.molecule_id === candidate) ?? 0,
  );
  const visibleData =
    data && paired ? { ...data, previews: [data.previews[candidateIndex]!] } : data;
  const visibleChoices = paired ? [choices[candidateIndex] ?? []] : choices;
  const error = useMemo(() => {
    if (!data) return null;
    try {
      matrixReadings(data, report);
      return null;
    } catch (failure) {
      return failure instanceof Error ? failure : new ContractError('$.matrix');
    }
  }, [data, report]);
  const { viewport, content, edges } = useScrollFocus<HTMLDivElement, HTMLTableElement>(
    'x',
    !!data,
  );
  function scrollPage(direction: -1 | 1) {
    if (viewport.current && content.current)
      moveMatrix(viewport.current, content.current, direction);
  }
  return (
    <section
      className={'sar-network-matrix' + (paired ? ' sar-matrix-paired' : '')}
      aria-label={t('结构对照')}
    >
      {resource.loading && <Loading />}
      {(resource.error || error) && (
        <SARFailure error={(resource.error ?? error)!} onRetry={resource.reload} />
      )}
      {data && visibleData && !error && (
        <>
          {paired && (
            <MatrixPairControls data={data} index={candidateIndex} onSelect={setCandidate} />
          )}
          <div ref={viewport} className="sar-matrix-viewport" aria-label={t('结构对照')}>
            <table ref={content} className="sar-matrix-table" aria-label={t('结构对照')}>
              <MatrixHead
                data={visibleData}
                sites={visibleChoices}
                siteOrder={siteOrder}
                jobId={jobId}
                active={active}
                onSource={onSource}
                onCompare={onCompare}
                onSelect={(molecule, region) =>
                  setChosen((old) => ({ ...old, [molecule]: region }))
                }
              />
              <MatrixValues data={visibleData} report={report} />
            </table>
          </div>
          {!paired && edges.overflow && (
            <div className="sar-matrix-controls">
              <button
                type="button"
                aria-label={t('向左查看结构')}
                disabled={!edges.start}
                onClick={() => scrollPage(-1)}
              >
                <ChevronLeft size={16} />
              </button>
              <button
                type="button"
                aria-label={t('向右查看结构')}
                disabled={!edges.end}
                onClick={() => scrollPage(1)}
              >
                <ChevronRight size={16} />
              </button>
            </div>
          )}
          <MatrixPredictions data={visibleData} />
        </>
      )}
    </section>
  );
}
