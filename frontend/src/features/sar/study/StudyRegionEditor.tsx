import { useState } from 'react';
import type { Dataset, Molecule, Region } from '../../../api/sarTypes';
import { useTranslation } from '../../../i18n';
import { MoleculeBrowser } from '../MoleculeBrowser';
import { RegionSelector } from '../RegionSelector';
export function StudyRegionEditor({
  dataset,
  regions,
  active,
  disabled,
  scope,
  onSaved,
}: {
  dataset: Dataset;
  regions: Region[];
  active: boolean;
  disabled: boolean;
  scope: string;
  onSaved: (region: Region) => void;
}) {
  const { t } = useTranslation();
  const [reference, setReference] = useState<Molecule | null>(null);
  const [name, setName] = useState('R' + (regions.length + 1));
  const [kind, setKind] = useState<'variable' | 'core'>('variable');
  const [open, setOpen] = useState(false);
  return (
    <details className="sar-compact" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>{t('新增命名区域')}</summary>
      <div hidden={!open}>
        <p className="sar-hint">{t('保存产生新的不可变区域；编辑不会覆盖已保存的区域。')}</p>
        <MoleculeBrowser
          dataset={dataset}
          active={active && open && !disabled}
          referenceId={reference?.id ?? null}
          onReference={setReference}
        />
        {reference && (
          <RegionSelector
            key={[reference.id, reference.graph_sha256, dataset.revision].join(':')}
            dataset={dataset}
            reference={reference}
            active={active && open}
            disabled={disabled}
            name={name}
            kind={kind}
            onNameChange={setName}
            onKindChange={setKind}
            highlights={regions}
            scope={scope}
            onRegion={ignoreRegion}
            onSaved={onSaved}
          />
        )}
      </div>
    </details>
  );
}
const ignoreRegion = () => {};
