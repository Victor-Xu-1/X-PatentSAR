import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, it, expect, vi } from 'vitest';
import { setLocale } from '../src/i18n';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { sarApi } from '../src/api/sarApi';
import { decodeStudyPreview } from '../src/api/sarPreviewDecoder';
import { TransformationPreview } from '../src/features/sar/study/TransformationPreview';
import { differenceText } from '../src/features/sar/study/PreviewMeasurements';
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
