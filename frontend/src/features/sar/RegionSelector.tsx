import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { sarApi } from '../../api/sarApi';
import type { Dataset, Molecule, Region, RegionRequest } from '../../api/sarTypes';
import { useSARResource } from './useSARResource';
import { ErrorNotice, Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { useTranslation } from '../../i18n';
import { safeDrawing } from './safeDrawing';
import { SourceLinks } from './SourceLinks';
import { MutationNotice } from './MutationNotice';
import { useRegionSave } from './useRegionSave';
import { RegionReadbackError } from './readSavedRegion';
import { MoleculeEvidence } from './MoleculeEvidence';
import { RegionLegend } from './study/RegionMap';
import { SelectionDrawing } from './SelectionDrawing';
import { useSelectionReveal } from './useSelectionReveal';

export function RegionSelector({
  dataset,
  reference,
  active,
  disabled: blocked = false,
  scope = '',
  name,
  kind,
  onNameChange,
  onKindChange,
  highlights = [],
  revealRequest = 0,
  onSaved,
  onRegion,
}: {
  dataset: Dataset;
  reference: Molecule;
  active: boolean;
  disabled?: boolean;
  scope?: string;
  name?: string;
  kind?: 'variable' | 'core';
  onNameChange?: (name: string) => void;
  onKindChange?: (kind: 'variable' | 'core') => void;
  highlights?: Region[];
  revealRequest?: number;
  onSaved?: (region: Region) => void;
  onRegion: (region: Region | null) => void;
}) {
  const { t } = useTranslation();
  const [indices, setIndices] = useState<number[]>([]);
  const [loadedURL, setLoadedURL] = useState<string | null>(null);
  const [failedURL, setFailedURL] = useState<string | null>(null);
  const [showHighlights, setShowHighlights] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const request: RegionRequest | null =
    reference.graph_sha256 && indices.length
      ? {
          molecule_id: reference.id,
          expected_dataset_revision: dataset.revision,
          expected_graph_sha256: reference.graph_sha256,
          atom_indices: [...indices],
          ...(name === undefined ? {} : { name }),
          ...(kind === undefined ? {} : { kind }),
        }
      : null;
  const saving = useRegionSave({
    datasetId: dataset.id,
    request,
    scope,
    active,
    onSaved: (region) => {
      onRegion(region);
      onSaved?.(region);
    },
  });
  const { mutation, saved } = saving;
  const load = useCallback(
    (signal: AbortSignal) => sarApi.drawing(dataset.id, reference.id, signal),
    [dataset.id, reference.id],
  );
  const drawing = useSARResource(
    `sar:drawing:${dataset.id}:${dataset.revision}:${reference.id}:${reference.graph_sha256}`,
    active && !blocked,
    load,
  );
  const image = useMemo(() => {
    if (!drawing.data) return { value: null, error: null };
    try {
      return { value: safeDrawing(drawing.data.svg), error: null };
    } catch (error) {
      return { value: null, error: error as Error };
    }
  }, [drawing.data]);
  const compatible = Boolean(
    drawing.data?.molecule.eligible &&
    reference.graph_sha256 &&
    drawing.data.molecule.graph_sha256 === reference.graph_sha256 &&
    drawing.data.atoms.length &&
    !dataset.stale,
  );
  const loaded = Boolean(image.value && loadedURL === image.value.url);
  const imageFailed = Boolean(image.value && failedURL === image.value.url);
  const graphCurrent = compatible && drawing.validated && !blocked;
  const savedCurrent =
    saved?.dataset_id === dataset.id &&
    saved.dataset_revision === dataset.revision &&
    saved.molecule_id === reference.id &&
    saved.graph_sha256 === reference.graph_sha256 &&
    (name === undefined || saved.name === name) &&
    (kind === undefined || saved.kind === kind);
  const disabled = !graphCurrent || !image.value || !loaded || imageFailed || mutation.locked;
  useSelectionReveal(panelRef, canvasRef, active, revealRequest, loaded);
  const compatibleHighlights = highlights.filter(
    (region) =>
      region.molecule_id === reference.id &&
      region.dataset_revision === dataset.revision &&
      region.graph_sha256 === reference.graph_sha256,
  );
  useEffect(() => {
    onRegion(graphCurrent && loaded && !image.error && !imageFailed && savedCurrent ? saved : null);
  }, [graphCurrent, loaded, image.error, imageFailed, savedCurrent, saved, onRegion]);
  function toggle(index: number) {
    setIndices((old) =>
      old.includes(index) ? old.filter((i) => i !== index) : [...old, index].sort((a, b) => a - b),
    );
    saving.clear();
    onRegion(null);
  }
  function save() {
    if (
      disabled ||
      !indices.length ||
      !reference.graph_sha256 ||
      (name !== undefined && (!name.trim() || name.length > 40))
    )
      return;
    if (!saving.canRecover) saving.save();
  }
  return (
    <section
      ref={panelRef}
      tabIndex={-1}
      className="sar-panel sar-selection-panel"
      aria-label={t('选择变化区域')}
    >
      <h2>
        {t('选择变化区域')} · {reference.label}
      </h2>
      {drawing.loading && <Loading />}
      <div className="sar-selection-fields">
        {onNameChange && (
          <label>
            {t('区域名称')}
            <input
              maxLength={40}
              value={name ?? ''}
              disabled={disabled}
              onChange={(event) => onNameChange(event.target.value)}
            />
          </label>
        )}
        {onKindChange && (
          <label>
            {t('选择用途')}
            <select
              value={kind ?? 'variable'}
              disabled={disabled}
              onChange={(event) => onKindChange(event.target.value as 'variable' | 'core')}
            >
              <option value="variable">{t('变化区域')}</option>
              <option value="core">{t('用户确认核心')}</option>
            </select>
          </label>
        )}
      </div>
      {drawing.error && <SARFailure error={drawing.error} onRetry={drawing.reload} />}
      {image.error && <SARFailure error={image.error} />}
      {imageFailed && <p role="alert">{t('RDKit 结构图加载失败。')}</p>}
      {drawing.validated && !compatible && (
        <p role="alert">{t('图或修订发生变化，已禁止使用旧选区。请刷新并重新选择。')}</p>
      )}
      {image.value && (
        <SelectionDrawing
          canvasRef={canvasRef}
          image={image.value}
          atoms={drawing.data?.atoms ?? []}
          regions={showHighlights ? compatibleHighlights : []}
          indices={indices}
          disabled={disabled}
          onToggle={toggle}
          onLoad={() => {
            setLoadedURL(image.value?.url ?? null);
            setFailedURL(null);
          }}
          onError={() => {
            setLoadedURL(null);
            setFailedURL(image.value?.url ?? null);
          }}
        />
      )}
      {!!compatibleHighlights.length && (
        <label className="sar-selection-overlay-toggle">
          <input
            type="checkbox"
            checked={showHighlights}
            onChange={(event) => setShowHighlights(event.target.checked)}
          />
          {t('显示已保存选区')}
        </label>
      )}
      {showHighlights && <RegionLegend regions={compatibleHighlights} />}
      <output>
        {indices.length
          ? t('已选原子：{indices}', { indices: indices.join(', ') })
          : t('尚未选择原子')}
      </output>
      <div className="sar-actions" hidden={saving.canRecover || saving.canResubmit}>
        <button
          type="button"
          disabled={disabled || !indices.length}
          onClick={() => {
            setIndices([]);
            saving.clear();
            onRegion(null);
          }}
        >
          {t('清除选区')}
        </button>
        <button
          type="button"
          className="primary"
          disabled={
            disabled ||
            !indices.length ||
            savedCurrent ||
            saving.canRecover ||
            (name !== undefined && !name.trim())
          }
          onClick={save}
        >
          {t(mutation.busy ? '正在保存…' : '保存区域')}
        </button>
      </div>
      {saved && savedCurrent && graphCurrent && loaded && !image.error && !imageFailed && (
        <output>{t('区域已保存 · {count} 个连接点', { count: saved.attachment_count })}</output>
      )}
      {(saving.canRecover || saving.canResubmit) && (
        <div className="sar-actions">
          {saving.canRecover && (
            <button
              type="button"
              disabled={!graphCurrent || !loaded || imageFailed || mutation.busy}
              onClick={saving.recover}
            >
              {t('检查已保存选区')}
            </button>
          )}
          {saving.canResubmit && (
            <button
              type="button"
              className="primary"
              disabled={!graphCurrent || !loaded || imageFailed || mutation.busy}
              onClick={saving.resubmit}
            >
              {t('重试保存同一选区')}
            </button>
          )}
        </div>
      )}
      {mutation.error instanceof RegionReadbackError ? (
        <ErrorNotice error={mutation.error} />
      ) : (
        <MutationNotice mutation={mutation} disabled={!graphCurrent} showSuccess={false} />
      )}
      <SourceLinks dataset={dataset} molecule={drawing.data?.molecule ?? reference} />
      {drawing.data && (
        <details>
          <summary>{t('来源详情')}</summary>
          <p className="sar-hint">
            {t('选择仅用于参考比较，不是结构修正。来源修正仍使用原项目的审计编辑器。')}
          </p>
          <MoleculeEvidence
            dataset={dataset}
            molecule={drawing.data.molecule}
            includeLinks={false}
          />
        </details>
      )}
    </section>
  );
}
