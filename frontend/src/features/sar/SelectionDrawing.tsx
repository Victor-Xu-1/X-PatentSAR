import type { RefObject } from 'react';
import type { Atom, Region } from '../../api/sarTypes';
import { useTranslation } from '../../i18n';
import { RegionMap } from './study/RegionMap';

/** Passive server geometry and exact native atom targets; no client chemistry or graph remapping. */
export function SelectionDrawing({
  canvasRef,
  image,
  atoms,
  regions,
  indices,
  disabled,
  onLoad,
  onError,
  onToggle,
}: {
  canvasRef: RefObject<HTMLDivElement | null>;
  image: { url: string; aspectRatio: string };
  atoms: Atom[];
  regions: Region[];
  indices: number[];
  disabled: boolean;
  onLoad: () => void;
  onError: () => void;
  onToggle: (index: number) => void;
}) {
  const { t } = useTranslation();
  return (
    <div ref={canvasRef} className="sar-drawing" style={{ aspectRatio: image.aspectRatio }}>
      <img
        key={image.url}
        src={image.url}
        alt={t('RDKit 参考结构')}
        onLoad={onLoad}
        onError={onError}
      />
      <RegionMap atoms={atoms} regions={regions} />
      {atoms.map((atom) => (
        <button
          key={atom.index}
          type="button"
          className="sar-atom"
          style={{ left: `${atom.x * 100}%`, top: `${atom.y * 100}%` }}
          aria-label={t('原子 {index}（{element}）', { index: atom.index, element: atom.element })}
          aria-pressed={indices.includes(atom.index)}
          disabled={disabled}
          onClick={() => onToggle(atom.index)}
        >
          <span aria-hidden="true">{atom.index}</span>
        </button>
      ))}
    </div>
  );
}
