import { act, render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, it, expect, vi } from 'vitest';
import { setLocale } from '../src/i18n';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { sarApi } from '../src/api/sarApi';
import { decodeStudyPreview } from '../src/api/sarPreviewDecoder';
import { TransformationPreview } from '../src/features/sar/study/TransformationPreview';
import { differenceText, PreviewMeasurements } from '../src/features/sar/study/PreviewMeasurements';
import { StudyRegions } from '../src/features/sar/study/StudyRegions';
import { propertyText } from '../src/features/sar/study/tablePresentation';
import {
  sarDataset,
  sarDrawing,
  sarPair,
  studyJob,
  studyReport,
  studyRow,
  studyContext,
} from './sar-fixtures';
const summary = studyReport.regions[0]!;
const candidate = { ...studyRow, molecule_id: 'candidate/control', label: 'I-2' };
const preview = {
  job: studyJob,
  region: summary.region,
  reference: studyRow,
  candidate,
  pair: {
    ...sarPair,
    reference_id: studyRow.molecule_id,
    molecule_id: candidate.molecule_id,
    region_id: summary.region.id,
    match_status: 'matched' as const,
  },
  measurements: [
    {
      context_id: studyContext.id,
      reference_values: ['10'],
      candidate_values: ['1'],
      comparison: 'better',
      evidence_basis: 'recorded_context',
      raw_difference: -9,
    },
  ],
  property_differences: { molecular_weight: 14.03 },
};
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarStudyApi, 'preview').mockResolvedValue(preview);
  vi.spyOn(sarStudyApi, 'drawing').mockResolvedValue({
    id: candidate.molecule_id,
    svg: sarDrawing.svg,
  });
  vi.spyOn(sarStudyApi, 'rows').mockResolvedValue({
    job: studyJob,
    items: [candidate],
    total: 1,
    page: 1,
    page_size: 50,
  });
  vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
});
describe('actual transformation preview', () => {
  it('reveals an explicitly opened preview once, respects reduced motion, and returns to its exact fragment', async () => {
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView');
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ matches: true })),
    );
    const report = {
      ...studyReport,
      regions: [
        {
          ...summary,
          fragments: [
            {
              ...summary.fragments[0]!,
              molecule_ids: [summary.region.molecule_id, candidate.molecule_id],
            },
          ],
        },
      ],
    };
    const original = JSON.stringify(report);
    render(<StudyRegions report={report} jobId={studyJob.id} active onRows={vi.fn()} />);
    const opener = await screen.findByRole('button', { name: 'Preview modification' });
    await userEvent.click(opener);
    const panel = screen.getByRole('region', { name: 'Transformation preview' });
    expect(panel).toHaveFocus();
    expect(scroll).toHaveBeenLastCalledWith({ block: 'start', behavior: 'auto' });
    await within(panel).findByText('Stronger');
    const revealed = scroll.mock.calls.length;
    await act(() => setLocale('zh-CN'));
    expect(panel).toHaveFocus();
    expect(scroll.mock.calls.length).toBe(revealed);
    await userEvent.click(screen.getByRole('button', { name: '关闭改造预览' }));
    expect(screen.queryByRole('region', { name: '改造预览' })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(JSON.stringify(report)).toBe(original);
  });
  it('reveals a repeated explicit preview click without replaying computation or a stale selection', async () => {
    const report = {
      ...studyReport,
      regions: [
        {
          ...summary,
          fragments: [
            {
              ...summary.fragments[0]!,
              molecule_ids: [summary.region.molecule_id, candidate.molecule_id],
            },
          ],
        },
      ],
    };
    render(<StudyRegions report={report} jobId={studyJob.id} active onRows={vi.fn()} />);
    const opener = await screen.findByRole('button', { name: 'Preview modification' });
    await userEvent.click(opener);
    await within(screen.getByRole('region', { name: 'Transformation preview' })).findByText(
      'Stronger',
    );
    const requests = vi.mocked(sarStudyApi.preview).mock.calls.length;
    await userEvent.click(opener);
    expect(screen.getByRole('region', { name: 'Transformation preview' })).toHaveFocus();
    expect(sarStudyApi.preview).toHaveBeenCalledTimes(requests);
  });
  it('retains table/header associations and source-owned mobile captions and units', () => {
    render(<PreviewMeasurements data={decodeStudyPreview(preview)} report={studyReport} />);
    const table = screen.getByRole('table', { name: 'Recorded activity' });
    expect(within(table).getByRole('columnheader', { name: studyRow.label })).toBeInTheDocument();
    expect(within(table).getByRole('rowheader', { name: 'IC50 原文 · nM' })).toBeInTheDocument();
    const captions = table.querySelectorAll('.sar-preview-compound-label');
    expect([...captions].map((item) => item.textContent)).toEqual([
      studyRow.label,
      candidate.label,
    ]);
    expect([...captions].every((item) => item.getAttribute('aria-hidden') === 'true')).toBe(true);
    expect(table.querySelector('.sar-preview-change')).toHaveTextContent('StrongerΔ -9.00');
  });
  it('does not steal focus when a hidden view is reactivated or a read is revalidated', async () => {
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView');
    const props = {
      report: studyReport,
      summary,
      moleculeId: candidate.molecule_id,
      jobId: studyJob.id,
      onSource: vi.fn(),
      onClose: vi.fn(),
      requestId: 1,
    };
    const { rerender } = render(
      <>
        <button type="button">Another control</button>
        <TransformationPreview {...props} active />
      </>,
    );
    const elsewhere = screen.getByRole('button', { name: 'Another control' });
    await within(screen.getByRole('region', { name: 'Transformation preview' })).findByText(
      'Stronger',
    );
    await userEvent.click(elsewhere);
    const revealed = scroll.mock.calls.length;
    rerender(
      <>
        <button type="button">Another control</button>
        <TransformationPreview {...props} active={false} />
      </>,
    );
    rerender(
      <>
        <button type="button">Another control</button>
        <TransformationPreview {...props} active />
      </>,
    );
    await within(screen.getByRole('region', { name: 'Transformation preview' })).findByText(
      'Stronger',
    );
    expect(elsewhere).toHaveFocus();
    expect(scroll.mock.calls.length).toBe(revealed);
  });
  it('can close a pending preview and restore the exact opener without waiting for its response', async () => {
    vi.mocked(sarStudyApi.preview).mockImplementation(() => new Promise(() => {}));
    const report = {
      ...studyReport,
      regions: [
        {
          ...summary,
          fragments: [
            {
              ...summary.fragments[0]!,
              molecule_ids: [summary.region.molecule_id, candidate.molecule_id],
            },
          ],
        },
      ],
    };
    render(<StudyRegions report={report} jobId={studyJob.id} active onRows={vi.fn()} />);
    const opener = await screen.findByRole('button', { name: 'Preview modification' });
    await userEvent.click(opener);
    await userEvent.click(screen.getByRole('button', { name: 'Close transformation preview' }));
    expect(
      screen.queryByRole('region', { name: 'Transformation preview' }),
    ).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
  it('does not pull the user back when pending data finishes after they move to another control', async () => {
    let finish: ((value: typeof preview) => void) | undefined;
    vi.mocked(sarStudyApi.preview).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView');
    render(
      <>
        <button type="button">Another control</button>
        <TransformationPreview
          report={studyReport}
          summary={summary}
          moleculeId={candidate.molecule_id}
          jobId={studyJob.id}
          active
          onSource={vi.fn()}
          onClose={vi.fn()}
        />
      </>,
    );
    const elsewhere = screen.getByRole('button', { name: 'Another control' });
    await userEvent.click(elsewhere);
    const revealed = scroll.mock.calls.length;
    await act(async () => finish?.(preview));
    await within(screen.getByRole('region', { name: 'Transformation preview' })).findByText(
      'Stronger',
    );
    expect(elsewhere).toHaveFocus();
    expect(scroll.mock.calls.length).toBe(revealed);
  });
  it('keeps censored values and indeterminate changes raw through language changes without a fabricated delta', async () => {
    const data = decodeStudyPreview({
      ...preview,
      measurements: [
        {
          ...preview.measurements[0]!,
          reference_values: ['<10'],
          candidate_values: ['<20'],
          comparison: 'indeterminate',
          raw_difference: null,
        },
      ],
    });
    const original = JSON.stringify(data);
    render(<PreviewMeasurements data={data} report={studyReport} />);
    const table = screen.getByRole('table', { name: 'Recorded activity' });
    expect(within(table).getByText('<10')).toBeVisible();
    expect(within(table).getByText('<20')).toBeVisible();
    expect(within(table).queryByText(/Δ/)).not.toBeInTheDocument();
    await act(() => setLocale('zh-CN'));
    expect(within(table).getByText('<10')).toBeVisible();
    expect(within(table).getByText('不可判定')).toBeVisible();
    expect(JSON.stringify(data)).toBe(original);
  });
  it('renders source scalars and backend differences, highlights exact region and keeps source selection', async () => {
    const onSource = vi.fn();
    render(
      <TransformationPreview
        report={studyReport}
        summary={summary}
        moleculeId={candidate.molecule_id}
        jobId={studyJob.id}
        active
        onSource={onSource}
        onClose={vi.fn()}
      />,
    );
    await screen.findByText('Stronger');
    expect(screen.getByText(/Δ -9.00/)).toBeVisible();
    expect(screen.getByText(/Δ 14.03/)).toBeVisible();
    await userEvent.click(screen.getAllByRole('button', { name: 'View original' })[1]!);
    expect(onSource).toHaveBeenCalledWith(candidate.molecule_id);
    expect(sarStudyApi.preview).toHaveBeenCalledWith(
      studyJob.id,
      sarDataset.id,
      summary.region.id,
      candidate.molecule_id,
      expect.any(AbortSignal),
    );
    await waitFor(() =>
      expect(sarStudyApi.drawing).toHaveBeenCalledWith(
        studyJob.id,
        'molecule',
        candidate.molecule_id,
        expect.any(AbortSignal),
        summary.region.id,
      ),
    );
  });
  it('rejects mismatched proof identity and nonfinite fabricated differences', () => {
    expect(decodeStudyPreview(preview).candidate.label).toBe('I-2');
    expect(() =>
      decodeStudyPreview({ ...preview, pair: { ...preview.pair, match_status: 'not_matched' } }),
    ).toThrow();
    expect(() =>
      decodeStudyPreview({ ...preview, property_differences: { molecular_weight: Infinity } }),
    ).toThrow();
    expect(differenceText(-0.00012)).toBe('-0.000120');
    expect(differenceText(null)).toBe('—');
    expect(propertyText(1, 'hydrogen_bond_donors')).toBe('1');
    expect(propertyText(2, 'hydrogen_bond_acceptors')).toBe('2');
    expect(propertyText(1.5, 'hydrogen_bond_donors')).toBe('1.50');
    expect(propertyText(250, 'molecular_weight')).toBe('250.00');
    expect(propertyText(null, 'hydrogen_bond_acceptors')).toBe('—');
  });
  it('switches a clicked region without starting computation and presents only the selected modification group', async () => {
    const second = {
      ...summary,
      region: { ...summary.region, id: 'a'.repeat(32), name: 'R2' },
      no_variation: true,
    };
    render(
      <StudyRegions
        report={{ ...studyReport, regions: [summary, second] }}
        jobId={studyJob.id}
        active
        onRows={vi.fn()}
      />,
    );
    await screen.findByRole('button', { name: 'R2' });
    await userEvent.click(screen.getByRole('button', { name: 'R2' }));
    expect(screen.getByRole('button', { name: 'R2' })).toHaveAttribute('aria-pressed', 'true');
    expect(sarStudyApi.preview).not.toHaveBeenCalled();
    expect(
      within(screen.getByText(/No structural variation/).parentElement!).getByText(
        /No structural variation/,
      ),
    ).toBeVisible();
  });
});
