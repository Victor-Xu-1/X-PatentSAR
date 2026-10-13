import { useRef, useState } from 'react';
import type { CatalogReport } from '../../../api/sarCatalogTypes';
import { useTranslation } from '../../../i18n';
import { StudyRegionMap } from './StudyRegionMap';
import { useInlineSelection } from '../../../components/useInlineSelection';
import { StudyRegionContent } from './StudyRegionContent';
export function StudyRegions({
  report,
  jobId,
  active,
  strongest = false,
  onRows,
  onSource = () => {},
}: {
  report: CatalogReport;
  jobId: string;
  active: boolean;
  strongest?: boolean;
  onRows: (region: string, fragment: string) => void;
  onSource?: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [selection, setSelection] = useState(report.regions[0]?.region.id ?? '');
  const selected =
    report.regions.find((summary) => summary.region.id === selection) ?? report.regions[0];
  const strip = useRef<HTMLDivElement>(null);
  useInlineSelection(strip, 'button[aria-pressed="true"]');
  return (
    <div className="sar-region-explorer">
      {!strongest && (
        <StudyRegionMap
          report={report}
          active={active}
          selected={selected?.region.id}
          onSelect={setSelection}
        />
      )}
      {strongest && (
        <div ref={strip} className="sar-region-selector">
          {report.regions.map((summary) => (
            <button
              key={summary.region.id}
              type="button"
              aria-pressed={selected?.region.id === summary.region.id}
              onClick={() => setSelection(summary.region.id)}
            >
              {summary.region.name}
            </button>
          ))}
        </div>
      )}
      {selected && (
        <StudyRegionContent
          key={selected.region.id}
          index={report.regions.indexOf(selected) + 1}
          summary={selected}
          jobId={jobId}
          active={active}
          strongest={strongest}
          onRows={onRows}
          report={report}
          onSource={onSource}
        />
      )}
      {!report.regions.length && <p>{t('本研究未选择区域。保存区域后可明确运行新研究。')}</p>}
    </div>
  );
}
