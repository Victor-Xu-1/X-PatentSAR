import type { CatalogReport } from '../../../api/sarCatalogTypes';
import { useCallback, useMemo } from 'react';
import type { Region } from '../../../api/sarTypes';

import { sarApi } from '../../../api/sarApi';
import { useTranslation } from '../../../i18n';
import { Loading } from '../../../components/Feedback';
import { SARFailure } from '../SARFailure';
import { useSARResource } from '../useSARResource';
import { safeDrawing } from '../safeDrawing';
import { RegionLegend, RegionMap } from './RegionMap';
import { StudyReferencePane } from './StudyReferencePane';
import { MolecularImage } from './MolecularImage';

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
  // A retained same-source drawing remains viewable, not authorization to use
  // stale controls or leave a top-layer chooser open after deactivation.
  const select =
    active && resource.validated && drawing.image && !drawing.error ? onSelect : undefined;
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
          <figure className="sar-study-image sar-reference-drawing">
            <MolecularImage
              image={drawing.image}
              identity={JSON.stringify(['sar:reference-drawing', datasetId, moleculeId])}
              label={label}
              authorized={active && resource.validated}
              inspectable
            >
              <RegionMap
                atoms={resource.data.atoms}
                regions={regions}
                selected={selected}
                onSelect={select}
              />
            </MolecularImage>
          </figure>
        </div>
      )}
      <RegionLegend regions={regions} selected={selected} onSelect={select} />
    </article>
  );
}

export function StudyRegionMap({
  report,
  active,
  selected,
  onSelect,
}: {
  report: CatalogReport;
  active: boolean;
  selected?: string | undefined;
  onSelect?: ((id: string) => void) | undefined;
}) {
  const { t } = useTranslation();
  const groups = useMemo(() => {
    const references = new Map<string, { label: string; regions: Region[] }>();
    for (const summary of report.regions) {
      const key = summary.region.molecule_id;
      const group = references.get(key) ?? { label: summary.reference_label, regions: [] };
      group.regions.push(summary.region);
      references.set(key, group);
    }
    return [...references.entries()].map(([id, group]) => ({ id, ...group }));
  }, [report.regions]);
  const current =
    groups.find((group) => group.regions.some((region) => region.id === selected)) ?? groups[0];
  if (!current) return null;
  return (
    <StudyReferencePane active={active}>
      {groups.length > 1 && (
        <label className="sar-reference-choice">
          {t('选择参考分子')}
          <select
            value={current.id}
            disabled={!active || !onSelect}
            onChange={(event) => {
              const next = groups.find((group) => group.id === event.target.value);
              if (next) onSelect?.(next.regions[0]!.id);
            }}
          >
            {groups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <ReferenceMap
        key={current.id}
        datasetId={report.dataset_id}
        regions={current.regions}
        label={current.label}
        active={active}
        selected={selected}
        onSelect={onSelect}
      />
    </StudyReferencePane>
  );
}
