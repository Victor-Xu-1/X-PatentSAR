import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { setLocale } from '../src/i18n';
import { decodeRegion, decodeDrawing } from '../src/api/sarDecoders';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { RegionSelector } from '../src/features/sar/RegionSelector';
import { readSavedRegion } from '../src/features/sar/readSavedRegion';
import { RegionMap, RegionLegend } from '../src/features/sar/study/RegionMap';
import { sarDataset, sarRegion, sarDrawing, sarMolecule, studyProfile } from './sar-fixtures';

beforeEach(() => setLocale('en'));
const region = {
  ...sarRegion,
  atom_indices: [],
  hydrogen_anchor: 0,
  name: 'H1',
  kind: 'variable' as const,
};

it('accepts source-bound hydrogen selections and rejects mixed, empty, core or ghost-atom shapes', () => {
  expect(decodeRegion(region)).toEqual(region);
  for (const broken of [
    { ...region, atom_indices: [0] },
    { ...region, hydrogen_anchor: null },
    { ...region, kind: 'core' },
    { ...region, hydrogen_anchor: 512 },
  ])
    expect(() => decodeRegion(broken)).toThrow();
  expect(decodeRegion(sarRegion)).toEqual(sarRegion);
  expect(() =>
    decodeDrawing({
      ...sarDrawing,
      atoms: sarDrawing.atoms.map((atom) => ({
        ...atom,
        hydrogen_site_supported: true,
        ordinary_hydrogens: 0,
      })),
    }),
  ).toThrow();
});

it('saves the original anchor rather than fabricating a hydrogen atom index', async () => {
  vi.spyOn(sarApi, 'drawing').mockResolvedValue({
    ...sarDrawing,
    atoms: sarDrawing.atoms.map((atom) => ({
      ...atom,
      ordinary_hydrogens: atom.index === 0 ? 3 : 0,
      hydrogen_site_supported: atom.index === 0,
    })),
  });
  const save = vi.spyOn(sarApi, 'saveRegion').mockResolvedValue(region);
  render(
    <RegionSelector
      dataset={sarDataset}
      reference={sarMolecule}
      active
      scope="hydrogen-selection"
      name="H1"
      onRegion={vi.fn()}
    />,
  );
  fireEvent.load(await screen.findByRole('img', { name: 'RDKit reference drawing' }));
  expect(screen.getByRole('checkbox', { name: 'H site' })).toBeDisabled();
  await userEvent.click(screen.getByRole('button', { name: 'Atom 0 (C)' }));
  await userEvent.click(screen.getByRole('checkbox', { name: 'H site' }));
  await userEvent.click(screen.getByRole('button', { name: 'Save region' }));
  expect(save.mock.calls[0]?.[1]).toMatchObject({
    atom_indices: [],
    hydrogen_anchor: 0,
    expected_graph_sha256: sarMolecule.graph_sha256,
  });
});

it('does not accept a different hydrogen site during uncertain-write readback', async () => {
  vi.spyOn(sarApi, 'dataset').mockResolvedValue(sarDataset);
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue({
    ...studyProfile,
    regions: [{ ...region, hydrogen_anchor: 1 }],
  });
  await expect(
    readSavedRegion(sarDataset.id, {
      molecule_id: region.molecule_id,
      expected_dataset_revision: region.dataset_revision,
      expected_graph_sha256: region.graph_sha256,
      atom_indices: [],
      hydrogen_anchor: 0,
      name: 'H1',
      kind: 'variable',
    }),
  ).rejects.toThrow();
});

it('uses a real-atom anchor with an H legend and pointer target, never an invented source atom', async () => {
  const onSelect = vi.fn();
  const original = JSON.stringify([region, sarDrawing.atoms]);
  const { container } = render(
    <>
      <RegionMap atoms={sarDrawing.atoms} regions={[region]} onSelect={onSelect} />
      <RegionLegend regions={[region]} onSelect={onSelect} />
    </>,
  );
  const hotspot = container.querySelector<HTMLButtonElement>('.sar-region-hotspots button')!;
  expect(hotspot).toBeInTheDocument();
  expect(container.querySelectorAll('.sar-region-hotspots button')).toHaveLength(1);
  await userEvent.click(screen.getByRole('button', { name: 'H1 · H' }));
  expect(onSelect).toHaveBeenLastCalledWith(region.id);
  expect(JSON.stringify([region, sarDrawing.atoms])).toBe(original);
});
