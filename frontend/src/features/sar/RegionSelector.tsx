import { useCallback, useEffect, useMemo, useState } from 'react';
import { sarApi } from '../../api/sarApi';
import type { Dataset, Molecule, Region, RegionRequest } from '../../api/sarTypes';
import { useResource } from '../../hooks/useResource';
import { Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { useTranslation } from '../../i18n';
import { safeDrawing } from './safeDrawing';
import { SourceLinks } from './SourceLinks';
import { MutationNotice } from './MutationNotice';
import { useSARMutation } from './useSARMutation';
import { MoleculeEvidence } from './MoleculeEvidence';

export function RegionSelector({
  dataset,
  reference,
  active,
  onRegion,
}: {
  dataset: Dataset;
  reference: Molecule;
  active: boolean;
  onRegion: (region: Region | null) => void;
}) {
  const { t } = useTranslation();
  const [indices, setIndices] = useState<number[]>([]);
  const [saved, setSaved] = useState<Region | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const mutation = useSARMutation();
  const load = useCallback(
    (signal: AbortSignal) => sarApi.drawing(dataset.id, reference.id, signal),
    [dataset.id, reference.id],
  );
  const drawing = useResource(
    active
      ? `sar:drawing:${dataset.id}:${dataset.revision}:${reference.id}:${reference.graph_sha256}`
      : null,
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
  const graphCurrent = Boolean(
    drawing.data?.molecule.eligible &&
    reference.graph_sha256 &&
    drawing.data.molecule.graph_sha256 === reference.graph_sha256 &&
    drawing.data.atoms.length &&
    !dataset.stale,
  );
  const disabled = !graphCurrent || !image.value || !loaded || mutation.locked;
  useEffect(() => {
    if (!graphCurrent || image.error || imageFailed) {
      onRegion(null);
    }
  }, [graphCurrent, image.error, imageFailed, onRegion]);
  function toggle(index: number) {
    setIndices((old) =>
      old.includes(index) ? old.filter((i) => i !== index) : [...old, index].sort((a, b) => a - b),
    );
    setSaved(null);
    onRegion(null);
  }
  function save() {
    if (disabled || !indices.length || !reference.graph_sha256) return;
    const payload: RegionRequest = {
      molecule_id: reference.id,
      expected_dataset_revision: dataset.revision,
      expected_graph_sha256: reference.graph_sha256,
      atom_indices: [...indices],
    };
    void mutation.run(
      () => sarApi.saveRegion(dataset.id, payload),
      (region) => {
        setSaved(region);
        onRegion(region);
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
      {drawing.error && (
        <SARFailure
          error={drawing.error}
          onRetry={() => {
            setLoaded(false);
            drawing.reload();
          }}
        />
      )}
      {image.error && <SARFailure error={image.error} />}
      {imageFailed && <p role="alert">{t('RDKit 结构图加载失败。')}</p>}
      {drawing.data && !graphCurrent && (
        <p role="alert">{t('图或修订发生变化，已禁止使用旧选区。请刷新并重新选择。')}</p>
      )}
      {image.value && (
        <div className="sar-drawing" style={{ aspectRatio: image.value.aspectRatio }}>
          <img
            src={image.value.url}
            alt={t('RDKit 参考结构')}
            onLoad={() => {
              setLoaded(true);
              setImageFailed(false);
            }}
            onError={() => {
              setLoaded(false);
              setImageFailed(true);
            }}
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
          disabled={disabled || !indices.length || Boolean(saved)}
          onClick={save}
        >
          {t(mutation.busy ? '正在保存…' : '保存区域')}
        </button>
      </div>
      {saved && graphCurrent && !image.error && !imageFailed && (
        <output>{t('区域已保存 · {count} 个连接点', { count: saved.attachment_count })}</output>
      )}
      <MutationNotice mutation={mutation} />
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
