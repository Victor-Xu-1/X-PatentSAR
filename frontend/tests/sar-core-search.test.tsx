import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { StudyNetwork } from '../src/features/sar/study/StudyNetwork';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { setLocale } from '../src/i18n';
import {
  sarDrawing,
  sarPair,
  studyFragment,
  studyJob,
  studyReport,
  studyRow,
} from './sar-fixtures';

const base = studyReport.regions[0]!;
const first = {
  ...base,
  matched: 2,
  no_variation: false,
  reference_label: 'Example 10',
  origin: 'single_site' as const,
  region: { ...base.region, id: 'site-first', atom_indices: [0] },
  fragments: [{ ...studyFragment, is_reference: false, molecule_ids: ['a', 'b'] }],
};
const other = {
  ...first,
  matched: 1,
  reference_label: 'Example 20',
  region: { ...base.region, id: 'site-other', molecule_id: 'other-core', atom_indices: [1] },
  fragments: [{ ...studyFragment, is_reference: false, molecule_ids: ['a'] }],
};
const report = { ...studyReport, regions: [first, other] };
const rows = ['a', 'b'].map((id) => ({ ...studyRow, molecule_id: id, label: 'Source ' + id }));
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
  vi.spyOn(sarStudyApi, 'drawing').mockImplementation(async (_job, _kind, id) => ({
    id,
    svg: sarDrawing.svg,
  }));
  vi.spyOn(sarStudyApi, 'rows').mockResolvedValue({
    job: studyJob,
    items: rows,
    total: 2,
    page: 1,
    page_size: 6,
  });
  vi.spyOn(sarStudyApi, 'matrix').mockImplementation(
    async (_job, _dataset, reference, selections) => ({
      reference_drawing: { id: reference, svg: sarDrawing.svg },
      previews: selections.map((selection) => ({
        job: studyJob,
        region: { ...base.region, id: selection.region_id, molecule_id: reference },
        reference: {
          ...studyRow,
          molecule_id: reference,
          label: reference === 'other-core' ? 'Example 20' : 'Example 10',
        },
        candidate: rows.find((row) => row.molecule_id === selection.molecule_id)!,
        pair: {
          ...sarPair,
          reference_id: reference,
          molecule_id: selection.molecule_id,
          region_id: selection.region_id,
          match_status: 'matched',
        },
        measurements: [
          {
            context_id: studyReport.policies[0]!.context_id,
            reference_values: ['<10'],
            candidate_values: ['<10'],
            comparison: 'indeterminate',
            evidence_basis: 'insufficient',
            raw_difference: null,
          },
        ],
        property_differences: {},
        drawings: {
          reference: { id: reference, svg: sarDrawing.svg },
          candidate: { id: selection.molecule_id, svg: sarDrawing.svg },
          layout: 'fixed_background',
          equivalent_mappings: 1,
          reason: null,
        },
      })),
    }),
  );
});

async function selected() {
  render(<StudyNetwork report={report} jobId={studyJob.id} active onSource={vi.fn()} />);
  await screen.findByRole('table', { name: 'Structure comparison' });
  const legend = document.querySelector('.sar-region-legend')!;
  await userEvent.click(within(legend as HTMLElement).getByRole('button', { name: 'R1' }));
  await waitFor(() =>
    expect(vi.mocked(sarStudyApi.rows).mock.calls.at(-1)?.[3].region_id).toBe('site-first'),
  );
  await screen.findByRole('table', { name: 'Structure comparison' });
  return screen.getByRole('textbox', { name: 'Find a core ID' });
}

it('filters the core gallery without changing an explicitly chosen reference, region or request pool', async () => {
  const original = JSON.stringify(report);
  const search = await selected();
  const reads = vi.mocked(sarStudyApi.rows).mock.calls.length;
  await userEvent.click(screen.getByRole('button', { name: 'Select core Example 10' }));
  expect(sarStudyApi.rows).toHaveBeenCalledTimes(reads);
  await userEvent.type(search, 'Example 20');
  expect(screen.getByRole('button', { name: 'Select core Example 20' })).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Select core Example 10' })).not.toBeInTheDocument();
  const table = screen.getByRole('table', { name: 'Structure comparison' });
  expect(table.querySelector('thead .sar-matrix-baseline strong')).toHaveTextContent('Example 10');
  expect(
    within(document.querySelector('.sar-region-legend') as HTMLElement).getByRole('button', {
      name: 'R1',
    }),
  ).toHaveAttribute('aria-pressed', 'true');
  expect(sarStudyApi.rows).toHaveBeenCalledTimes(reads);
  await userEvent.click(screen.getByRole('button', { name: 'Select core Example 20' }));
  await waitFor(() =>
    expect(vi.mocked(sarStudyApi.rows).mock.calls.at(-1)?.[3]).toMatchObject({
      reference_id: 'other-core',
      region_id: '',
    }),
  );
  await waitFor(() =>
    expect(
      screen
        .getByRole('table', { name: 'Structure comparison' })
        .querySelector('thead .sar-matrix-baseline strong'),
    ).toHaveTextContent('Example 20'),
  );
  expect(JSON.stringify(report)).toBe(original);
});

it('keeps the comparison usable through no-result, clear, locale and ordering changes', async () => {
  const search = await selected();
  const reads = vi.mocked(sarStudyApi.rows).mock.calls.length;
  await userEvent.type(search, 'unmatched-core-query');
  expect(
    screen
      .getByRole('table', { name: 'Structure comparison' })
      .querySelector('thead .sar-matrix-baseline strong'),
  ).toHaveTextContent('Example 10');
  expect(screen.getByText('No matching cores')).toBeVisible();
  await userEvent.clear(search);
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Core order' }), 'identifier');
  await act(() => setLocale('zh-CN'));
  expect(
    screen
      .getByRole('table', { name: '结构对照' })
      .querySelector('thead .sar-matrix-baseline strong'),
  ).toHaveTextContent('Example 10');
  expect(sarStudyApi.rows).toHaveBeenCalledTimes(reads);
});
