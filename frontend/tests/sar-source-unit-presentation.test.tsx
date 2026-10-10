import { render, screen } from '@testing-library/react';
import { act } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { setLocale } from '../src/i18n';
import { sarApi } from '../src/api/sarApi';
import { MoleculeBrowser } from '../src/features/sar/MoleculeBrowser';
import { MoleculeEvidence } from '../src/features/sar/MoleculeEvidence';
import { contextLabel } from '../src/features/sar/presentation';
import { sarDataset, sarMolecule } from './sar-fixtures';

beforeEach(() => setLocale('en'));

it.each([
  ['IC50', 'nM', 'IC50 · nM'],
  ['IC50 (nM)', 'nM', 'IC50 (nM)'],
  ['IC50 nM', 'nM', 'IC50 nM'],
  ['IC50 (nM)', 'µM', 'IC50 (nM) · µM'],
  ['IC50', null, 'IC50'],
  ['IC50', '', 'IC50'],
  ['原文 +++', null, '原文 +++'],
] as const)('preserves exact label and unit boundaries for %s / %s', (name, unit, expected) => {
  const source = { name, unit };
  expect(contextLabel(source)).toBe(expected);
  expect(source).toEqual({ name, unit });
});

it.each(['en', 'zh-CN'] as const)(
  'does not duplicate a source-owned metric unit in the reference list or source record in %s',
  async (locale) => {
    setLocale(locale);
    const dataset = {
      ...sarDataset,
      metrics: [{ ...sarDataset.metrics[0]!, name: 'IC50 原文 (nM)' }],
    };
    const original = JSON.stringify([dataset, sarMolecule]);
    vi.spyOn(sarApi, 'molecules').mockResolvedValue({
      items: [sarMolecule],
      page: 1,
      page_size: 50,
      total: 1,
    });
    const view = render(
      <MoleculeBrowser dataset={dataset} active referenceId={null} onReference={vi.fn()} />,
    );
    const row = (await screen.findByRole('rowheader', { name: sarMolecule.label })).closest('tr')!;
    expect(row.querySelector('td:nth-of-type(2)')).toHaveTextContent(/^IC50 原文 \(nM\): <10$/);
    view.unmount();
    render(<MoleculeEvidence dataset={dataset} molecule={sarMolecule} />);
    const observation = document.querySelector('.sar-evidence > ul > li')!;
    expect(observation).toHaveTextContent('IC50 原文 (nM): <10');
    expect(observation).not.toHaveTextContent('<10 · nM');
    expect(JSON.stringify([dataset, sarMolecule])).toBe(original);
  },
);

it('shows distinct source and observation units without converting, hiding or reconciling them', async () => {
  const dataset = {
    ...sarDataset,
    metrics: [{ ...sarDataset.metrics[0]!, name: 'IC50 原文 (nM)' }],
  };
  const molecule = {
    ...sarMolecule,
    observations: [{ ...sarMolecule.observations[0]!, unit: 'µM', value: '> 0.025' }],
  };
  const original = JSON.stringify([dataset, molecule]);
  render(<MoleculeEvidence dataset={dataset} molecule={molecule} />);
  expect(document.querySelector('.sar-evidence > ul > li')).toHaveTextContent(
    'IC50 原文 (nM) · µM: > 0.025',
  );
  await act(() => setLocale('zh-CN'));
  expect(document.querySelector('.sar-evidence > ul > li')).toHaveTextContent(
    'IC50 原文 (nM) · µM: > 0.025',
  );
  expect(JSON.stringify([dataset, molecule])).toBe(original);
});
