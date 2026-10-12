import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { decodeStudyPreview } from '../src/api/sarPreviewDecoder';
import { TransformationPreview } from '../src/features/sar/study/TransformationPreview';
import { StudyImage } from '../src/features/sar/study/StudyImage';
import { setLocale } from '../src/i18n';
import { sarDrawing, sarPair, studyJob, studyReport, studyRow } from './sar-fixtures';

const summary = studyReport.regions[0]!;
const candidates = [
  { ...studyRow, molecule_id: 'candidate-2', label: 'P2' },
  { ...studyRow, molecule_id: 'candidate-3', label: 'P3' },
];
const packet = (id = candidates[0]!.molecule_id) => {
  const candidate = candidates.find((row) => row.molecule_id === id)!;
  return {
    job: studyJob,
    region: summary.region,
    reference: studyRow,
    candidate,
    pair: {
      ...sarPair,
      reference_id: studyRow.molecule_id,
      molecule_id: id,
      region_id: summary.region.id,
      match_status: 'matched' as const,
    },
    measurements: [],
    property_differences: {},
    drawings: {
      layout: 'fixed_background',
      equivalent_mappings: 2,
      reason: null,
      reference: { id: studyRow.molecule_id, svg: sarDrawing.svg },
      candidate: {
        id,
        svg: sarDrawing.svg.replace('80,150', id === 'candidate-2' ? '90,150' : '100,150'),
      },
    },
  };
};

beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarStudyApi, 'drawing').mockResolvedValue({ id: 'legacy', svg: sarDrawing.svg });
  vi.spyOn(sarStudyApi, 'preview').mockImplementation(async (_j, _d, _r, id) =>
    decodeStudyPreview(packet(id)),
  );
  vi.spyOn(sarStudyApi, 'rows').mockResolvedValue({
    items: candidates,
    total: 2,
    page: 1,
    page_size: 50,
    job: studyJob,
  });
});

function show() {
  return render(
    <TransformationPreview
      report={studyReport}
      summary={summary}
      moleculeId={candidates[0]!.molecule_id}
      jobId={studyJob.id}
      active
      onSource={vi.fn()}
      onClose={vi.fn()}
    />,
  );
}

it('uses the exact paired source drawings, not two independently scaled fetches', async () => {
  show();
  const panel = screen.getByRole('region', { name: 'Transformation preview' });
  await within(panel).findByRole('img', { name: 'P2' });
  expect(sarStudyApi.drawing).not.toHaveBeenCalled();
  const image = within(panel).getByRole('img', { name: 'P2' });
  fireEvent.load(image);
  fireEvent.load(within(panel).getByRole('img', { name: studyRow.label }));
  await userEvent.click(within(panel).getByRole('button', { name: 'Enlarge structure P2' }));
  expect(screen.getByRole('dialog')).toBeVisible();
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('dialog')).toBeVisible();
  expect(within(screen.getByRole('dialog')).getByRole('img', { name: 'P2' })).toHaveAttribute(
    'src',
    image.getAttribute('src'),
  );
});

it('retains paired layout metadata and refuses mismatched or unsupported alignment claims', () => {
  const source = packet();
  expect(decodeStudyPreview(source)).toHaveProperty('drawings', source.drawings);
  expect(
    decodeStudyPreview({ ...source, drawings: { ...source.drawings, layout: 'fixed_component' } })
      .drawings?.layout,
  ).toBe('fixed_component');
  for (const drawings of [
    { ...source.drawings, candidate: { ...source.drawings.candidate, id: 'foreign' } },
    { ...source.drawings, equivalent_mappings: 0 },
    { ...source.drawings, equivalent_mappings: 65 },
    { ...source.drawings, layout: 'fixed_background', reason: 'depiction_failed' },
    { ...source.drawings, layout: 'guessed' },
    { ...source.drawings, reference: { ...source.drawings.reference, svg: '' } },
  ])
    expect(() => decodeStudyPreview({ ...source, drawings })).toThrow();
  const { drawings: _drawings, ...legacy } = source;
  expect(decodeStudyPreview(legacy).candidate.label).toBe('P2');
});

it('shows explicit independent-layout status rather than claiming alignment after failure', async () => {
  const source = packet();
  vi.mocked(sarStudyApi.preview).mockResolvedValue(
    decodeStudyPreview({
      ...source,
      drawings: { ...source.drawings, layout: 'independent', reason: 'depiction_failed' },
    }),
  );
  show();
  expect(await screen.findByRole('status', { name: 'Drawing layout' })).toHaveTextContent(
    'Independent layouts',
  );
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('status', { name: '绘图布局' })).toHaveTextContent('独立布局');
});

it('does not display active server markup or replace a refused paired drawing with an independent fetch', async () => {
  const source = packet();
  vi.mocked(sarStudyApi.preview).mockResolvedValue(
    decodeStudyPreview({
      ...source,
      drawings: {
        ...source.drawings,
        candidate: {
          ...source.drawings.candidate,
          svg: '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="320"><script>bad()</script></svg>',
        },
      },
    }),
  );
  show();
  expect(await screen.findByRole('alert')).toBeVisible();
  expect(screen.queryByRole('img', { name: 'P2' })).not.toBeInTheDocument();
  expect(sarStudyApi.drawing).not.toHaveBeenCalled();
});

it('refuses a foreign provided drawing at the shared image boundary', () => {
  render(
    <StudyImage
      jobId={studyJob.id}
      kind="molecule"
      identifier={studyRow.molecule_id}
      label={studyRow.label}
      active
      providedDrawing={{ id: 'foreign', svg: sarDrawing.svg }}
    />,
  );
  expect(screen.getByRole('alert')).toBeVisible();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(sarStudyApi.drawing).not.toHaveBeenCalled();
});
