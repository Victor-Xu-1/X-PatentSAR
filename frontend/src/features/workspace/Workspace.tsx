import { useState } from 'react';
import type { Compound, Filters, Health, Job, Project } from '../../api/types';
import type { Route } from '../../model/route';
import { withoutActivityFocus } from '../../model/route';
import { withTableQuery } from '../../model/tableQueryRoute';
import { validActivityFocus } from '../../api/activitySourceDecoders';
import { normalizeLayout } from '../../model/layout';
import { PdfPane } from '../pdf/PdfPane';
import { CropDialog } from '../results/CropDialog';
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
  const [editing, setEditing] = useState<Compound | null>(null);
  const [exporting, setExporting] = useState(false);
  const [legacyActivityPage, setLegacyActivityPage] = useState<number | null>(null);
  const id = project?.id ?? null;
  const results = useResultsState(id, query, onQuery, job, onProjectReload, route.tableQuery);
  const currentCrop = crop
    ? (results.resource.data?.items.find((row) => row.id === crop.id) ?? crop)
    : null;
  const layout = normalizeLayout(route.layout);
  function navigateSource(patch: Partial<Route>, clearTableQuery = false) {
    setLegacyActivityPage(null);
    const next = { ...withoutActivityFocus(route), ...patch };
    if (clearTableQuery) delete next.tableQuery;
    navigate(next);
  }
  function changeFilters(patch: Partial<Filters>) {
    results.changeFilters(patch);
    if (
      patch.column_filters !== undefined ||
      patch.sort_column !== undefined ||
      patch.sort_direction !== undefined ||
      patch.sort_band !== undefined
    )
      navigate(withTableQuery(route, { ...results.filters, ...patch }));
  }
  function jump(row: Compound) {
    if (row.source.page !== null)
      navigateSource({
        page: row.source.page,
        tab: 'annotations',
        compoundId: row.id,
        layout: { ...layout, pdfVisible: true },
      });
  }
  function selectAnnotation(compoundId: string) {
    const locating = results.locateCompound(compoundId);
    navigateSource(
      {
        tab: 'annotations',
        compoundId,
        resultTab: 'results',
        layout: { ...layout, pdfVisible: true },
      },
      locating,
    );
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
            activityFocus={route.activityFocus}
            activityPageOnly={legacyActivityPage !== null && route.page === legacyActivityPage}
            onPage={(page) => navigateSource({ page, compoundId: null })}
            onTab={(tab) => navigateSource({ tab })}
            onSelect={selectAnnotation}
            onAttach={onAttach}
          />
        }
        results={
          <ResultViews
            tab={route.resultTab ?? 'results'}
            onTab={(resultTab) => navigateSource({ resultTab })}
            capabilities={capabilities}
            onSource={(page) =>
              navigateSource({
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
              onFilters: changeFilters,
              onSelect: results.toggle,
              onSelectPage: results.selectPage,
              onJump: jump,
              onActivitySource: (row, activity, key) => {
                if (activity.page !== null) {
                  const focus = { compoundId: row.id, key: key ?? '' };
                  setLegacyActivityPage(validActivityFocus(focus) ? null : activity.page);
                  navigate({
                    ...withoutActivityFocus(route),
                    page: activity.page,
                    tab: 'original',
                    compoundId: null,
                    ...(validActivityFocus(focus) ? { activityFocus: focus } : {}),
                    layout: { ...layout, pdfVisible: true },
                  });
                }
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
      {currentCrop && id && (
        <CropDialog
          projectId={id}
          compound={currentCrop}
          available={capabilities?.admet ?? null}
          onClose={() => setCrop(null)}
        />
      )}
      {editing && id && (
        <CorrectionDialog
          projectId={id}
          compound={editing}
          activityColumns={results.resource.data?.activity_columns}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            navigateSource({});
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
