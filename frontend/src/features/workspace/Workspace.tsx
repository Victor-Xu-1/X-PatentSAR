import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import type { Compound, Filters, Job, Project } from '../../api/types';
import type { Route } from '../../model/route';
import { activeJob } from '../../model/presentation';
import { useResource } from '../../hooks/useResource';
import { useDebounced } from '../../hooks/useDebounced';
import { PdfPane } from '../pdf/PdfPane';
import { ResultsPane } from '../results/ResultsPane';
import { CropDialog } from '../results/CropDialog';
import { ReviewDialog } from '../results/ReviewDialog';
import { ExportDialog } from '../results/ExportDialog';
import { JobActions } from '../jobs/JobActions';
import { StageStrip } from '../jobs/StageStrip';

export function Workspace({
  project,
  route,
  navigate,
  query,
  onQuery,
  ready,
  job,
  onJobChange,
  onProjectReload,
  onUpload,
  onAttach,
}: {
  project: Project | null;
  route: Route;
  navigate: (route: Route) => void;
  query: string;
  onQuery: (q: string) => void;
  ready: boolean;
  job: Job | null;
  onJobChange: () => void;
  onProjectReload: () => void;
  onUpload: () => void;
  onAttach: () => void;
}) {
  const [baseFilters, setBaseFilters] = useState({
    confidence: '',
    review: '',
    target: '',
    page: 1,
    page_size: 10,
  });
  const [metric, setMetric] = useState('');
  const [selected, setSelected] = useState(new Set<string>());
  const [crop, setCrop] = useState<Compound | null>(null);
  const [review, setReview] = useState<Compound | null>(null);
  const [exporting, setExporting] = useState(false);
  const [previousQuery, setPreviousQuery] = useState(query);
  if (previousQuery !== query) {
    setPreviousQuery(query);
    setBaseFilters((old) => ({ ...old, page: 1 }));
    setSelected(new Set());
  }
  const debouncedQuery = useDebounced(query);
  const id = project?.id ?? null;
  const filters: Filters = { ...baseFilters, q: debouncedQuery };
  const filtersKey = JSON.stringify(filters);
  const load = useCallback(
    (signal: AbortSignal) => api.results(id ?? '', JSON.parse(filtersKey) as Filters, signal),
    [id, filtersKey],
  );
  const resource = useResource(id ? `results:${id}:${filtersKey}` : null, load);
  const reloadResults = resource.reload;
  const refreshed = useRef<string | null>(null);
  useEffect(() => {
    if (job && !activeJob(job) && refreshed.current !== `${job.id}:${job.status}`) {
      refreshed.current = `${job.id}:${job.status}`;
      reloadResults();
      onProjectReload();
    }
  }, [job, onProjectReload, reloadResults]);
  function changeFilters(patch: Partial<Filters>) {
    if (patch.q !== undefined) onQuery(patch.q);
    const { q: _query, ...rest } = patch;
    setBaseFilters((old) => ({ ...old, ...rest }));
    if (
      patch.q !== undefined ||
      patch.target !== undefined ||
      patch.confidence !== undefined ||
      patch.review !== undefined
    )
      setSelected(new Set());
  }
  function toggle(id: string) {
    setSelected((old) => {
      const next = new Set(old);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function selectPage(checked: boolean) {
    setSelected((old) => {
      const next = new Set(old);
      resource.data?.items.forEach((row) => {
        if (checked) next.add(row.id);
        else next.delete(row.id);
      });
      return next;
    });
  }
  function jump(row: Compound) {
    if (row.source.page !== null)
      navigate({ ...route, page: row.source.page, tab: 'annotations', compoundId: row.id });
  }
  function selectAnnotation(compoundId: string) {
    navigate({ ...route, tab: 'annotations', compoundId });
    if (!resource.data?.items.some((row) => row.id === compoundId)) {
      onQuery(compoundId);
      setBaseFilters({ confidence: '', review: '', target: '', page: 1, page_size: 10 });
      setSelected(new Set());
    }
  }
  return (
    <div className="workspace">
      <section className="workflow-panel">
        <StageStrip job={job} />
        <JobActions project={project} job={job} ready={ready} onChange={onJobChange} />
      </section>
      <div className="workspace-split">
        <PdfPane
          key={id}
          project={project}
          page={route.page}
          tab={route.tab}
          selectedId={route.compoundId}
          onPage={(page) => navigate({ ...route, page, compoundId: null })}
          onTab={(tab) => navigate({ ...route, tab })}
          onSelect={selectAnnotation}
          onAttach={onAttach}
        />
        <ResultsPane
          project={project}
          resource={resource}
          filters={{ ...filters, q: query }}
          metric={metric}
          selected={selected}
          focusedId={route.compoundId}
          onMetric={setMetric}
          onFilters={changeFilters}
          onSelect={toggle}
          onSelectPage={selectPage}
          onJump={jump}
          onCrop={setCrop}
          onReview={setReview}
          onExport={() => setExporting(true)}
          onUpload={onUpload}
        />
      </div>
      {crop && <CropDialog compound={crop} onClose={() => setCrop(null)} />}
      {review && id && (
        <ReviewDialog
          projectId={id}
          compound={review}
          onClose={() => setReview(null)}
          onSaved={() => {
            setReview(null);
            resource.reload();
            onProjectReload();
          }}
        />
      )}
      {exporting && project && (
        <ExportDialog
          project={project}
          selected={[...selected]}
          filters={{ ...filters, q: query }}
          onClose={() => setExporting(false)}
        />
      )}
    </div>
  );
}
