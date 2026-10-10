import { useEffect, useId, useRef, useState } from 'react';
import type { Dataset } from '../../../api/sarTypes';
import type { StudyFilter, StudyReport, StudyRow } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { StudyOverview } from './StudyOverview';
import { StudyScaffolds } from './StudyScaffolds';
import { StudyLeads } from './StudyLeads';
import { StudyRegions } from './StudyRegions';
import { StudyActivityTable } from './StudyActivityTable';
import { StudySource } from './StudySource';
import { selectedContexts } from './tablePresentation';
import { StudyViewTabs } from './StudyViewTabs';
import { preferredScrollBehavior } from '../../../model/motion';
const tabs = [
  '研究概览',
  '研究骨架',
  '研究先导候选',
  '变化区域',
  '片段汇总',
  '研究活性表',
] as const;
export function StudyReportView({
  report,
  dataset,
  jobId,
  active,
}: {
  report: StudyReport;
  dataset: Dataset;
  jobId: string;
  active: boolean;
}) {
  const { t } = useTranslation(),
    id = useId();
  const sourceOwner = JSON.stringify([jobId, dataset.id, dataset.revision, report.input_sha256]);
  const rowsPanel = useRef<HTMLElement>(null),
    revealedRows = useRef(0);
  const [rowsRequest, setRowsRequest] = useState(0);
  const [tab, setTab] = useState(0),
    [source, setSource] = useState<{ owner: string; id: string; row: StudyRow | null } | null>(
      null,
    );
  if (source && source.owner !== sourceOwner) setSource(null);
  const [filter, setFilter] = useState<StudyFilter>({
    query: '',
    scope: 'all',
    scaffold_id: '',
    region_id: '',
    fragment_id: '',
  });
  useEffect(() => {
    if (revealedRows.current === rowsRequest) return;
    revealedRows.current = rowsRequest;
    if (!active || tab !== 5 || !rowsPanel.current) return;
    // Only an explicit member choice transfers focus. Later reads, locale
    // changes and ordinary tab visits must not steal the user's current focus.
    rowsPanel.current.focus({ preventScroll: true });
    rowsPanel.current.scrollIntoView({ block: 'start', behavior: preferredScrollBehavior() });
  }, [active, rowsRequest, tab]);
  function showRows(patch: Partial<StudyFilter>) {
    setFilter((old) => ({ ...old, ...patch }));
    setTab(5);
    setRowsRequest((request) => request + 1);
  }
  function showSource(id: string, row?: StudyRow) {
    setSource({
      owner: sourceOwner,
      id,
      row: row ?? report.candidates.find((r) => r.molecule_id === id) ?? null,
    });
  }
  return (
    <div className="sar-study-report">
      <StudyViewTabs labels={tabs} selected={tab} panelId={id} onSelect={setTab} />
      <section id={id + '-0'} hidden={tab !== 0} aria-label={t(tabs[0])}>
        <StudyOverview report={report} />
      </section>
      <section id={id + '-1'} hidden={tab !== 1} aria-label={t(tabs[1])}>
        <StudyScaffolds
          report={report}
          jobId={jobId}
          active={active && tab === 1}
          onRows={(scaffold_id) =>
            showRows({ scaffold_id, scope: 'all', region_id: '', fragment_id: '' })
          }
        />
      </section>
      <section id={id + '-2'} hidden={tab !== 2} aria-label={t(tabs[2])}>
        <StudyLeads
          report={report}
          jobId={jobId}
          active={active && tab === 2}
          onSource={showSource}
        />
      </section>
      <section id={id + '-3'} hidden={tab !== 3} aria-label={t(tabs[3])}>
        <StudyRegions
          report={report}
          jobId={jobId}
          active={active && tab === 3}
          onRows={(region_id, fragment_id) =>
            showRows({ region_id, fragment_id, scaffold_id: '', scope: 'all' })
          }
          onSource={showSource}
        />
      </section>
      <section id={id + '-4'} hidden={tab !== 4} aria-label={t(tabs[4])}>
        <StudyRegions
          report={report}
          jobId={jobId}
          active={active && tab === 4}
          strongest
          onRows={(region_id, fragment_id) =>
            showRows({ region_id, fragment_id, scaffold_id: '', scope: 'all' })
          }
          onSource={showSource}
        />
      </section>
      <section
        id={id + '-5'}
        ref={rowsPanel}
        tabIndex={-1}
        hidden={tab !== 5}
        aria-label={t(tabs[5])}
      >
        <StudyActivityTable
          report={report}
          jobId={jobId}
          active={active && tab === 5}
          filter={filter}
          onFilter={setFilter}
          onSource={showSource}
        />
      </section>
      {source && (
        <StudySource
          dataset={dataset}
          id={source.id}
          row={source.row}
          contexts={selectedContexts(report)}
          active={active}
          onClose={() => setSource(null)}
        />
      )}
    </div>
  );
}
