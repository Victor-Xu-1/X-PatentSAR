import { expect, it } from 'vitest';
import { coreChoices, orderCores } from '../src/features/sar/study/coreChoices';
import { studyFragment, studyReport } from './sar-fixtures';

it('counts unique published non-reference alternatives without counting regions or aliases twice', () => {
  const base = studyReport.regions[0]!;
  const summaries = [
    {
      ...base,
      reference_label: 'Example 10',
      region: { ...base.region, molecule_id: 'ref-10' },
      fragments: [
        { ...studyFragment, is_reference: false, molecule_ids: ['a', 'b', 'a', 'ref-10'] },
      ],
    },
    {
      ...base,
      reference_label: 'Example 2',
      region: { ...base.region, molecule_id: 'ref-2' },
      fragments: [{ ...studyFragment, is_reference: false, molecule_ids: ['a', 'b', 'c'] }],
    },
    {
      ...base,
      reference_label: 'Example 10',
      region: { ...base.region, id: 'other', molecule_id: 'ref-10' },
      fragments: [{ ...studyFragment, is_reference: false, molecule_ids: ['b'] }],
    },
  ];
  const original = JSON.stringify(summaries);
  const cores = coreChoices({ ...studyReport, discovery: null, regions: summaries });
  expect(cores.map((core) => [core.label, core.alternativeCount])).toEqual([
    ['Example 10', 2],
    ['Example 2', 3],
  ]);
  expect(orderCores(cores, 'alternatives').map((core) => core.label)).toEqual([
    'Example 2',
    'Example 10',
  ]);
  expect(orderCores(cores, 'identifier').map((core) => core.label)).toEqual([
    'Example 2',
    'Example 10',
  ]);
  expect(JSON.stringify(summaries)).toBe(original);
});

it('retains manual no-variation cores and resolves equal counts with natural original-label order', () => {
  const base = studyReport.regions[0]!;
  const cores = coreChoices({
    ...studyReport,
    discovery: null,
    regions: ['10', '2', '8A'].map((label) => ({
      ...base,
      reference_label: label,
      region: { ...base.region, molecule_id: label },
      no_variation: true,
      fragments: [{ ...studyFragment, is_reference: true }],
    })),
  });
  expect(orderCores(cores, 'alternatives').map((core) => core.label)).toEqual(['2', '8A', '10']);
  expect(cores).toHaveLength(3);
});
