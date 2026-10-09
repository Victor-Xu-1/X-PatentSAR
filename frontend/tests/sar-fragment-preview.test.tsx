import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { setLocale } from '../src/i18n';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { StudyRegions } from '../src/features/sar/study/StudyRegions';
import { StudySetup } from '../src/features/sar/study/StudySetup';
import { ChartLegend } from '../src/features/sar/study/StudyComposition';
import { chartColor } from '../src/features/sar/study/chartPresentation';
import { RegionLegend } from '../src/features/sar/study/RegionMap';
import type { StudyBin } from '../src/api/sarStudyTypes';
import { namedRegion, sarDataset, studyContext, studyProfile, studyReport } from './sar-fixtures';

beforeEach(() => setLocale('en'));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it('presents all four captured comparison counts without a synthetic ratio or zero/missing confusion', async () => {
  const original = JSON.stringify(studyReport);
  render(
    <StudyRegions report={studyReport} jobId="study-control" active={false} onRows={vi.fn()} />,
  );
  const strip = screen.getByRole('group', { name: 'Reference-comparison results' });
  for (const [label, value] of [
    ['Stronger', '0'],
    ['Weaker', '1'],
    ['Indeterminate', '1'],
    ['Missing', '0'],
  ] as const) {
    expect(within(within(strip).getByText(label).closest('div')!).getByText(value!)).toBeVisible();
  }
  await act(() => setLocale('zh-CN'));
  expect(within(strip).getByText('更弱')).toBeVisible();
  expect(within(strip).getByText('未确定')).toBeVisible();
  expect(JSON.stringify(studyReport)).toBe(original);
});

it('limits a visible fragment legend without reindexing the shared colour domain', () => {
  const bins: StudyBin[] = [
    { label: '[1,2)', kind: 'numeric', molecules: 0, observations: 0, strong: true },
    { label: '[2,3)', kind: 'numeric', molecules: 1, observations: 2, strong: false },
    { label: 'missing', kind: 'missing', molecules: 1, observations: 1, strong: false },
  ];
  const original = JSON.stringify(bins);
  render(<ChartLegend bins={bins} visibleBins={bins.slice(1)} direction="higher" />);
  const list = screen.getByRole('list', { name: 'Activity legend' });
  expect(within(list).queryByText('[1, 2)')).not.toBeInTheDocument();
  const retained = within(list).getByText('[2, 3)');
  const color = retained.querySelector('span')!.style.background;
  const reference = document.createElement('span');
  const expected = chartColor(bins[1]!, 1, 'higher');
  if (expected === undefined) throw new Error('Missing colour at the retained domain index');
  reference.style.background = expected;
  expect(color).toBe(reference.style.background);
  expect(within(list).getByText('No activity recorded')).toBeVisible();
  expect(JSON.stringify(bins)).toBe(original);
});

it('retains the historical observation unit when choosing visible fragment categories', () => {
  const original = studyReport.regions[0]!;
  const bin = {
    label: 'observed-only',
    kind: 'ordinal' as const,
    molecules: 0,
    observations: 2,
    strong: false,
  };
  const report = {
    ...studyReport,
    distributions: [{ ...studyReport.distributions[0]!, bins: [bin] }],
    regions: [{ ...original, fragments: [{ ...original.fragments[0]!, bins: [bin] }] }],
  };
  render(<StudyRegions report={report} jobId="study-control" active={false} onRows={vi.fn()} />);
  expect(screen.getByRole('combobox', { name: 'Counting unit' })).toHaveValue('observations');
  const visibleLegend = screen
    .getAllByRole('list', { name: 'Activity legend' })
    .find((list) => !list.closest('details'))!;
  expect(visibleLegend).toBeVisible();
  expect(within(visibleLegend).getByText('observed-only')).toBeVisible();
});

it('reuses source-owned context labels in the review step without a repeated unit', async () => {
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue({
    ...studyProfile,
    contexts: [{ ...studyContext, name: 'IC50 原文 (nM)' }],
  });
  render(<StudySetup dataset={sarDataset} active disabled={false} scope="owned" onJob={vi.fn()} />);
  await userEvent.click(await screen.findByRole('checkbox', { name: /IC50 原文 \(nM\)/ }));
  await userEvent.selectOptions(screen.getByLabelText('Activity direction'), 'lower');
  await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
  expect(document.querySelector('.sar-selected-contexts li')).toHaveTextContent(
    /^IC50 原文 \(nM\)$/,
  );
  await act(() => setLocale('zh-CN'));
  expect(document.querySelector('.sar-selected-contexts li')).toHaveTextContent(
    /^IC50 原文 \(nM\)$/,
  );
});

it('reveals the current raw region label only within its own selection strip', () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    const list = this.closest('ul');
    return (
      this.tagName === 'UL'
        ? { left: 0, right: 200, width: 200 }
        : { left: 240 - (list?.scrollLeft ?? 0), right: 360 - (list?.scrollLeft ?? 0), width: 120 }
    ) as DOMRect;
  });
  const originalFocus = document.activeElement;
  render(
    <RegionLegend
      regions={[namedRegion, { ...namedRegion, id: 'second', name: 'R2 原文' }]}
      selected="second"
      onSelect={vi.fn()}
    />,
  );
  const strip = screen.getByRole('button', { name: 'R2 原文' }).closest('ul')!;
  expect(strip.scrollLeft).toBe(160);
  expect(document.activeElement).toBe(originalFocus);
  expect(window.scrollY).toBe(0);
});
