import { useState, type ReactNode } from 'react';
import type { Dataset, Molecule } from '../../api/sarTypes';
import { useTranslation } from '../../i18n';
import { MoleculeBrowser } from './MoleculeBrowser';

/** One explicit chooser for both study and single-reference comparisons. */
export function ReferenceWorkspace({
  dataset,
  reference,
  active,
  disabled,
  onReference,
  children,
}: {
  dataset: Dataset;
  reference: Molecule | null;
  active: boolean;
  disabled: boolean;
  onReference: (molecule: Molecule) => void;
  children: (selection: { active: boolean; revealRequest: number }) => ReactNode;
}) {
  const { t } = useTranslation();
  const [choosing, setChoosing] = useState(!reference);
  const [revealRequest, setRevealRequest] = useState(0);
  function revealSelection() {
    setChoosing(false);
    setRevealRequest((request) => request + 1);
  }
  return (
    <div className="sar-reference-workspace">
      <div hidden={!choosing}>
        {reference && (
          <button type="button" onClick={revealSelection} disabled={!active}>
            {t('返回选区')}
          </button>
        )}
        <MoleculeBrowser
          dataset={dataset}
          active={active && choosing && !disabled}
          referenceId={reference?.id ?? null}
          onReference={(molecule) => {
            onReference(molecule);
            revealSelection();
          }}
        />
      </div>
      {reference && (
        <div hidden={choosing}>
          <div className="sar-reference-toolbar">
            <button type="button" onClick={() => setChoosing(true)} disabled={!active || disabled}>
              {t('更换参考')}
            </button>
          </div>
          {children({ active: active && !choosing, revealRequest })}
        </div>
      )}
    </div>
  );
}
