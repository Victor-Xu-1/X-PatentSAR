import { useMemo, useState } from 'react';
import type { Atom, Region } from '../../../api/sarTypes';
import { Dialog } from '../../../components/Dialog';
import { useTranslation } from '../../../i18n';
import { regionMarker } from './regionMarker';
import { regionPointerTargets } from './regionPointerTargets';

type RegionHotspotProps = {
  atoms: Atom[];
  regions: Region[];
  colors: readonly string[];
  selected?: string | undefined;
  onSelect: (id: string) => void;
};

export function RegionHotspots(props: RegionHotspotProps) {
  const owner = useMemo(
    () => JSON.stringify([props.atoms, props.regions]),
    [props.atoms, props.regions],
  );
  return <RegionPointerControls key={owner} {...props} />;
}

function RegionPointerControls({ atoms, regions, colors, selected, onSelect }: RegionHotspotProps) {
  const { t } = useTranslation();
  const targets = useMemo(() => regionPointerTargets(atoms, regions), [atoms, regions]);
  const [choice, setChoice] = useState<number | null>(null);
  const current = targets.find((target) => target.atom.index === choice);
  const first = current?.choices.find((item) => item.region.id === selected) ?? current?.choices[0];
  return (
    <>
      <div className="sar-region-hotspots">
        {targets.map((target) => {
          const single = target.choices.length === 1;
          const chosen =
            target.choices.find((item) => item.region.id === selected) ?? target.choices[0]!;
          const marker = regionMarker(chosen.region, chosen.order);
          return (
            <button
              type="button"
              tabIndex={-1}
              key={target.atom.index}
              data-atom-index={target.atom.index}
              data-region-id={single ? chosen.region.id : undefined}
              data-region-ids={JSON.stringify(target.choices.map((item) => item.region.id))}
              aria-label={
                single
                  ? marker.description + ' · ' + target.atom.element + ' ' + target.atom.index
                  : t('原子 {index}（{element}）· {count} 个变化区域', {
                      index: target.atom.index,
                      element: target.atom.element,
                      count: target.choices.length,
                    })
              }
              aria-pressed={target.choices.some((item) => item.region.id === selected)}
              aria-haspopup={single ? undefined : 'dialog'}
              aria-expanded={single ? undefined : current?.atom.index === target.atom.index}
              onClick={() => {
                if (single) onSelect(chosen.region.id);
                else setChoice(target.atom.index);
              }}
              style={{
                left: target.atom.x * 100 + '%',
                top: target.atom.y * 100 + '%',
                color: colors[chosen.order % colors.length],
              }}
            />
          );
        })}
      </div>
      {current && (
        <Dialog
          title={
            t('变化区域') +
            ' · ' +
            t('原子 {index}（{element}）', {
              index: current.atom.index,
              element: current.atom.element,
            })
          }
          className="sar-region-choice-dialog"
          onClose={() => setChoice(null)}
        >
          <div className="dialog-body sar-region-choice-grid">
            {current.choices.map((item) => {
              const marker = regionMarker(item.region, item.order);
              const label =
                (item.region.name ?? marker.marker) +
                (item.region.hydrogen_anchor == null ? '' : ' · H');
              return (
                <button
                  type="button"
                  key={item.region.id}
                  data-region-id={item.region.id}
                  data-initial-focus={item === first ? true : undefined}
                  aria-label={label}
                  aria-pressed={item.region.id === selected}
                  title={marker.description}
                  onClick={() => {
                    onSelect(item.region.id);
                    setChoice(null);
                  }}
                >
                  <span style={{ background: colors[item.order % colors.length] }} />
                  {marker.description}
                </button>
              );
            })}
          </div>
        </Dialog>
      )}
    </>
  );
}
