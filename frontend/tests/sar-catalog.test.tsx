import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { decodeStudyCatalog, decodeStudyReport } from '../src/api/sarStudyDecoders';
import { verifyRegionDetail } from '../src/api/sarStudyIntegrity';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { StudyRegionContent } from '../src/features/sar/study/StudyRegionContent';
import { setLocale } from '../src/i18n';
import { catalogBody, coherentCatalogReport as coherentReport } from './sar-catalog-fixtures';
import { studyJob, studyRow, studyFragment, sarDrawing } from './sar-fixtures';

it('keeps every exact member and count without pretending catalog entries contain fragment chemistry or bins', () => {
  const full = coherentReport(),
    wire = catalogBody(full);
  const decoded = decodeStudyCatalog(wire);
  expect(decoded.report.regions).toEqual(wire.report.regions);
  expect(Object.keys(decoded.report.regions[0]!.fragments[0]!)).toEqual([
    'id',
    'molecule_ids',
    'molecule_count',
    'is_reference',
    'representation',
  ]);
  expect(() => decodeStudyReport(wire.report)).toThrow();
  expect(() => decodeStudyCatalog({ ...wire, detail: undefined })).toThrow();
  expect(() => decodeStudyCatalog({ ...wire, detail: 'full' })).toThrow();
  expect(decodeStudyReport(full).regions[0]!.fragments[0]!.smiles).toBe(studyFragment.smiles);
  expect(() => verifyRegionDetail(decoded.report, full.regions[0]!)).not.toThrow();
});

it('rejects missing, duplicate, foreign or miscounted indexed members and mismatched source receipts', () => {
  const full = coherentReport();
  for (const mutate of [
    (v: ReturnType<typeof catalogBody>) => {
      v.report.regions[0]!.fragments.pop();
    },
    (v: ReturnType<typeof catalogBody>) => {
      v.report.regions[0]!.fragments[1]!.molecule_ids = [studyRow.molecule_id];
    },
    (v: ReturnType<typeof catalogBody>) => {
      v.report.regions[0]!.fragments[1]!.molecule_ids = ['foreign'];
    },
    (v: ReturnType<typeof catalogBody>) => {
      v.report.regions[0]!.fragments[1]!.molecule_count = 8;
    },
    (v: ReturnType<typeof catalogBody>) => {
      v.activity_basis.source_input_sha256 = 'f'.repeat(64);
    },
    (v: ReturnType<typeof catalogBody>) => {
      v.report.regions[0]!.region = { ...v.report.regions[0]!.region, dataset_revision: 9 };
    },
  ]) {
    const wire = catalogBody(full);
    mutate(wire);
    expect(() => decodeStudyCatalog(wire)).toThrow();
  }
});

it('requires source-bound details and full-domain bins, independent of JSON field order', () => {
  const full = coherentReport(),
    catalog = decodeStudyCatalog(catalogBody(full)).report;
  const region = full.regions[0]!;
  expect(() =>
    verifyRegionDetail(
      catalog,
      Object.fromEntries(Object.entries(region).reverse()) as typeof region,
    ),
  ).not.toThrow();
  const foreign = structuredClone(region);
  foreign.region.graph_sha256 = 'f'.repeat(64);
  expect(() => verifyRegionDetail(catalog, foreign)).toThrow();
  const badBins = structuredClone(region);
  badBins.fragments[0]!.bins[0]!.molecules = 10;
  expect(() => verifyRegionDetail(catalog, badBins)).toThrow();
});

it('reads details only for an active region, shows failures explicitly and retries without any scientific write', async () => {
  setLocale('en');
  const full = coherentReport(),
    wire = catalogBody(full);
  const region = vi
    .spyOn(sarStudyApi, 'region')
    .mockRejectedValueOnce(new Error('read refused'))
    .mockResolvedValue({
      job: studyJob,
      region: full.regions[0]!,
      activity_basis: wire.activity_basis,
    });
  vi.spyOn(sarStudyApi, 'drawing').mockResolvedValue({ id: studyFragment.id, svg: sarDrawing.svg });
  const start = vi.spyOn(sarStudyApi, 'start');
  const props = {
    summary: wire.report.regions[0]!,
    report: wire.report,
    index: 1,
    jobId: studyJob.id,
    strongest: false,
    onRows: vi.fn(),
    onSource: vi.fn(),
  };
  const view = render(<StudyRegionContent {...props} active={false} />);
  expect(region).not.toHaveBeenCalled();
  view.rerender(<StudyRegionContent {...props} active />);
  expect(await screen.findByRole('alert')).toHaveTextContent('read refused');
  expect(screen.queryByRole('heading', { name: /Fragment 1/ })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Reload' }));
  expect(await screen.findByRole('heading', { name: /Fragment 1/ })).toBeVisible();
  await act(() => setLocale('zh-CN'));
  await waitFor(() => expect(region).toHaveBeenCalledTimes(2));
  expect(start).not.toHaveBeenCalled();
});
