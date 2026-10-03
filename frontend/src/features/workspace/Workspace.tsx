import { useState } from 'react';
import type { Compound, Health, Job, Project } from '../../api/types';
import type { Route } from '../../model/route';
import { normalizeLayout } from '../../model/layout';
import { PdfPane } from '../pdf/PdfPane';
import { CropDialog } from '../results/CropDialog';
import { ReviewDialog } from '../results/ReviewDialog';
import { CorrectionDialog } from '../results/CorrectionDialog';
import { ExportDialog } from '../results/ExportDialog';
import { JobActions } from '../jobs/JobActions';
import { StageStrip } from '../jobs/StageStrip';
import { WorkspaceLayout } from './WorkspaceLayout';
import { ResultViews } from './ResultViews';
import { useResultsState } from './useResultsState';

export function Workspace({
  project,
  route,
  navigate,
  query,
  onQuery,
  ready,
  capabilities = null,
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
  onQuery: (query: string) => void;
  ready: boolean;
  capabilities?: Health['capabilities'] | null;
  job: Job | null;
  onJobChange: () => void;
  onProjectReload: () => void;
  onUpload: () => void;
  onAttach: () => void;
}) {
  const [crop, setCrop] = useState<Compound | null>(null);
  const [review, setReview] = useState<Compound | null>(null);
  const [editing, setEditing] = useState<Compound | null>(null);
  const [exporting, setExporting] = useState(false);
  const id = project?.id ?? null;
  const results = useResultsState(id, query, onQuery, job, onProjectReload);
  const layout = normalizeLayout(route.layout);
  function jump(row: Compound) {
    if (row.source.page !== null)
      navigate({
        ...route,
        page: row.source.page,
        tab: 'annotations',
        compoundId: row.id,
        layout: { ...layout, pdfVisible: true },
      });
  }
  function selectAnnotation(compoundId: string) {
    navigate({
      ...route,
      tab: 'annotations',
      compoundId,
      resultTab: 'results',
      layout: { ...layout, pdfVisible: true },
    });
    results.locateCompound(compoundId);
  }
  return (
    <div className="workspace" data-dialog-focus-scope>
      <section className="workflow-panel">
        <StageStrip job={job} compact />
        <JobActions project={project} job={job} ready={ready} onChange={onJobChange} compact />
      </section>
      <WorkspaceLayout
        layout={layout}
        onChange={(layout) => navigate({ ...route, layout })}
        source={
          <PdfPane
            key={id}
            project={project}
            page={route.page ?? project?.first_structure_page ?? null}
            tab={route.tab}
            selectedId={route.compoundId}
            onPage={(page) => navigate({ ...route, page, compoundId: null })}
            onTab={(tab) => navigate({ ...route, tab })}
            onSelect={selectAnnotation}
            onAttach={onAttach}
          />
        }
        results={
          <ResultViews
            tab={route.resultTab ?? 'results'}
            onTab={(resultTab) => navigate({ ...route, resultTab })}
            capabilities={capabilities}
            onSource={(page) =>
              navigate({
                ...route,
                page,
                tab: 'annotations',
                compoundId: null,
                layout: { ...layout, pdfVisible: true },
              })
            }
            resultProps={{
              project,
              job,
              resource: results.resource,
              filters: { ...results.filters, q: query },
              selected: results.selected,
              focusedId: route.compoundId,
              onFilters: results.changeFilters,
              onSelect: results.toggle,
              onSelectPage: results.selectPage,
              onJump: jump,
              onActivitySource: (activity) => {
                if (activity.page !== null)
                  navigate({
                    ...route,
                    page: activity.page,
                    tab: 'original',
                    compoundId: null,
                    layout: { ...layout, pdfVisible: true },
                  });
              },
              onCrop: setCrop,
              onReview: setEditing,
              onExport: () => setExporting(true),
              onUpload,
              canPredict: Boolean(capabilities?.admet),
              onPredictionQueued: onJobChange,
            }}
          />
        }
      />
      {crop && id && (
        <CropDialog
          projectId={id}
          compound={crop}
          available={capabilities?.admet ?? null}
          onClose={() => setCrop(null)}
        />
      )}
      {review && id && (
        <ReviewDialog
          projectId={id}
          compound={review}
          onClose={() => setReview(null)}
          onSaved={() => {
            setReview(null);
            results.resource.reload();
            onProjectReload();
          }}
        />
      )}
      {editing && id && (
        <CorrectionDialog
          projectId={id}
          compound={editing}
          onClose={() => setEditing(null)}
          onReview={() => {
            setReview(editing);
            setEditing(null);
          }}
          onSaved={() => {
            setEditing(null);
            results.resource.reload();
            onProjectReload();
            onJobChange();
          }}
        />
      )}
      {exporting && project && (
        <ExportDialog
          project={project}
          selected={[...results.selected]}
          filters={{ ...results.filters, q: query }}
          onClose={() => setExporting(false)}
        />
      )}
    </div>
  );
}
