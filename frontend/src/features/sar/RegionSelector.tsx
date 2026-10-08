import { useCallback, useEffect, useMemo, useState } from 'react';
import { sarApi } from '../../api/sarApi';
import type { Dataset, Molecule, Region, RegionRequest } from '../../api/sarTypes';
import { useSARResource } from './useSARResource';
import { Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { useTranslation } from '../../i18n';
import { safeDrawing } from './safeDrawing';
import { SourceLinks } from './SourceLinks';
import { MutationNotice } from './MutationNotice';
import { useSARMutation } from './useSARMutation';
import { MoleculeEvidence } from './MoleculeEvidence';
import { RegionLegend, RegionMap } from './study/RegionMap';

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
  onSaved?: (region: Region) => void;
  onRegion: (region: Region | null) => void;
}) {
  const { t } = useTranslation();
  const [indices, setIndices] = useState<number[]>([]);
  const [saved, setSaved] = useState<Region | null>(null);
  const [loadedURL, setLoadedURL] = useState<string | null>(null);
  const [failedURL, setFailedURL] = useState<string | null>(null);
  const mutation = useSARMutation({
    active,
    scope: JSON.stringify([
      scope,
      dataset.id,
      dataset.revision,
      reference.id,
      reference.graph_sha256,
      name,
      kind,
    ]),
  });
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
  useEffect(() => {
    onRegion(graphCurrent && loaded && !image.error && !imageFailed && savedCurrent ? saved : null);
  }, [graphCurrent, loaded, image.error, imageFailed, savedCurrent, saved, onRegion]);
  function toggle(index: number) {
    setIndices((old) =>
      old.includes(index) ? old.filter((i) => i !== index) : [...old, index].sort((a, b) => a - b),
    );
    setSaved(null);
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
    const payload: RegionRequest = {
      molecule_id: reference.id,
      expected_dataset_revision: dataset.revision,
      expected_graph_sha256: reference.graph_sha256,
      atom_indices: [...indices],
      ...(name === undefined ? {} : { name }),
      ...(kind === undefined ? {} : { kind }),
    };
    void mutation.run(
      () => sarApi.saveRegion(dataset.id, payload),
      (region) => {
        setSaved(region);
        onRegion(region);
        onSaved?.(region);
      },
    );
  }
  return (
    <section className="sar-panel" aria-label={t('选择变化区域')}>
      <h2>
        {t('选择变化区域')} · {reference.label}
      </h2>
      <p className="sar-hint">
        {t('选择仅用于参考比较，不是结构修正。来源修正仍使用原项目的审计编辑器。')}
      </p>
      {drawing.loading && <Loading />}
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
      {drawing.error && <SARFailure error={drawing.error} onRetry={drawing.reload} />}
      {image.error && <SARFailure error={image.error} />}
      {imageFailed && <p role="alert">{t('RDKit 结构图加载失败。')}</p>}
      {drawing.validated && !compatible && (
        <p role="alert">{t('图或修订发生变化，已禁止使用旧选区。请刷新并重新选择。')}</p>
      )}
      {image.value && (
        <div className="sar-drawing" style={{ aspectRatio: image.value.aspectRatio }}>
          <img
            key={image.value.url}
            src={image.value.url}
            alt={t('RDKit 参考结构')}
            onLoad={() => {
              setLoadedURL(image.value?.url ?? null);
              setFailedURL(null);
            }}
            onError={() => {
              setLoadedURL(null);
              setFailedURL(image.value?.url ?? null);
            }}
          />
          <RegionMap
            atoms={drawing.data?.atoms ?? []}
            regions={highlights.filter(
              (r) =>
                r.molecule_id === reference.id &&
                r.dataset_revision === dataset.revision &&
                r.graph_sha256 === reference.graph_sha256,
            )}
          />
          {drawing.data?.atoms.map((atom) => (
            <button
              key={atom.index}
              type="button"
              className="sar-atom"
              style={{ left: `${atom.x * 100}%`, top: `${atom.y * 100}%` }}
              aria-label={t('原子 {index}（{element}）', {
                index: atom.index,
                element: atom.element,
              })}
              aria-pressed={indices.includes(atom.index)}
              disabled={disabled}
              onClick={() => toggle(atom.index)}
            >
              <span>{atom.index}</span>
            </button>
          ))}
        </div>
      )}
      <RegionLegend
        regions={highlights.filter(
          (r) =>
            r.molecule_id === reference.id &&
            r.dataset_revision === dataset.revision &&
            r.graph_sha256 === reference.graph_sha256,
        )}
      />
      <output>
        {indices.length
          ? t('已选原子：{indices}', { indices: indices.join(', ') })
          : t('尚未选择原子')}
      </output>
      <div className="sar-actions">
        <button
          type="button"
          disabled={disabled || !indices.length}
          onClick={() => {
            setIndices([]);
            setSaved(null);
            onRegion(null);
          }}
        >
          {t('清除选区')}
        </button>
        <button
          type="button"
          className="primary"
          disabled={
            disabled || !indices.length || savedCurrent || (name !== undefined && !name.trim())
          }
          onClick={save}
        >
          {t(mutation.busy ? '正在保存…' : '保存区域')}
        </button>
      </div>
      {saved && savedCurrent && graphCurrent && loaded && !image.error && !imageFailed && (
        <output>{t('区域已保存 · {count} 个连接点', { count: saved.attachment_count })}</output>
      )}
      <MutationNotice mutation={mutation} disabled={!graphCurrent} />
      <SourceLinks dataset={dataset} molecule={drawing.data?.molecule ?? reference} />
      {drawing.data && (
        <details>
          <summary>{t('来源详情')}</summary>
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
