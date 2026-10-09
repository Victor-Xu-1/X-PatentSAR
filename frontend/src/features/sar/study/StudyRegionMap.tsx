import { useCallback, useMemo } from 'react';
import type { Region } from '../../../api/sarTypes';
import type { StudyReport } from '../../../api/sarStudyTypes';
import { sarApi } from '../../../api/sarApi';
import { useTranslation } from '../../../i18n';
import { Loading } from '../../../components/Feedback';
import { SARFailure } from '../SARFailure';
import { useSARResource } from '../useSARResource';
import { safeDrawing } from '../safeDrawing';
import { RegionLegend, RegionMap } from './RegionMap';

function ReferenceMap({
  datasetId,
  regions,
  label,
  active,
  selected,
  onSelect,
}: {
  datasetId: string;
  regions: Region[];
  label: string;
  active: boolean;
  selected?: string | undefined;
  onSelect?: ((id: string) => void) | undefined;
}) {
  const { t } = useTranslation();
  const moleculeId = regions[0]!.molecule_id;
  const load = useCallback(
    (signal: AbortSignal) => sarApi.drawing(datasetId, moleculeId, signal),
    [datasetId, moleculeId],
  );
  const resource = useSARResource(
    'sar:combined-region-map:' + datasetId + ':' + moleculeId,
    active,
    load,
  );
  const drawing = useMemo(() => {
    try {
      if (!resource.data) return { image: null, error: null };
      if (regions.some((region) => region.graph_sha256 !== resource.data!.molecule.graph_sha256))
        throw new Error('Region graph differs from the immutable reference');
      return { image: safeDrawing(resource.data.svg), error: null };
    } catch (error) {
      return { image: null, error: error as Error };
    }
  }, [resource.data, regions]);
  return (
    <article className="sar-reference-map-card">
      <div className="sar-section-heading">
        <h3>
          {t('参考分子区域总览')} · {label}
        </h3>
        <span>
          {regions.length} {t('变化区域')}
        </span>
      </div>
      {resource.loading && <Loading />}
      {resource.error && <SARFailure error={resource.error} onRetry={resource.reload} />}
      {drawing.error && <SARFailure error={drawing.error} />}
      {drawing.image && resource.data && (
        <div className="sar-reference-map-image" style={{ aspectRatio: drawing.image.aspectRatio }}>
          <img src={drawing.image.url} alt={label} />
          <RegionMap
            atoms={resource.data.atoms}
            regions={regions}
            selected={selected}
            onSelect={onSelect}
          />
        </div>
      )}
      <RegionLegend regions={regions} selected={selected} onSelect={onSelect} />
      {onSelect && <small className="sar-hint">{t('点击结构区域，查看改造与数据变化。')}</small>}
    </article>
  );
}

export function StudyRegionMap({
  report,
  active,
  selected,
  onSelect,
}: {
  report: StudyReport;
  active: boolean;
  selected?: string | undefined;
  onSelect?: ((id: string) => void) | undefined;
}) {
  const groups = new Map<string, { label: string; regions: Region[] }>();
  for (const summary of report.regions) {
    const key = summary.region.molecule_id;
    const group = groups.get(key) ?? { label: summary.reference_label, regions: [] };
    group.regions.push(summary.region);
    groups.set(key, group);
  }
  return (
    <div className="sar-reference-maps">
      {[...groups.entries()].map(([key, group]) => (
        <ReferenceMap
          key={key}
          datasetId={report.dataset_id}
          regions={group.regions}
          label={group.label}
          active={active}
          selected={selected}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
