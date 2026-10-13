import { useState } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import type { Dataset, SARJob } from '../src/api/sarTypes';
import type { StudyReport } from '../src/api/sarStudyTypes';
import { ApiError } from '../src/api/errors';
import { UncertainSARWrite } from '../src/api/sarMutation';
import { setLocale } from '../src/i18n';
import { emptyRoute } from '../src/model/route';
import { SARPage } from '../src/features/sar/SARPage';
import { sarDataset, studyJob, studyProfile, studyReport, studyContext } from './sar-fixtures';

function mount(
  report: StudyReport = studyReport,
  dataset: Dataset = sarDataset,
  otherJobs: SARJob[] = [],
) {
  setLocale('en');
  const old = { ...studyJob, stale: true };
  vi.spyOn(sarApi, 'datasets').mockResolvedValue({ items: [dataset], total: 1 });
  vi.spyOn(sarApi, 'dataset').mockResolvedValue(dataset);
  vi.spyOn(sarApi, 'jobs').mockResolvedValue({
    items: [old, ...otherJobs],
    total: 1 + otherJobs.length,
  });
  vi.spyOn(sarApi, 'job').mockResolvedValue(old);
  vi.spyOn(sarStudyApi, 'overview').mockResolvedValue({ job: old, report });
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue(studyProfile);
  const start = vi.spyOn(sarStudyApi, 'start').mockResolvedValue({ ...studyJob, id: 'new-study' });
  function Harness() {
    const [route, setRoute] = useState({
      ...emptyRoute,
      view: 'sar' as const,
      sarDatasetId: dataset.id,
      sarJobId: studyJob.id,
    });
    return <SARPage active route={route} navigate={(next) => setRoute(next as typeof route)} />;
  }
  render(<Harness />);
  return start;
}
async function prepare() {
  const action = await screen.findByRole('button', { name: 'New analysis' });
  await waitFor(() => expect(action).toBeEnabled());
  await userEvent.click(action);
  const run = await screen.findByRole('button', { name: 'Run full study' });
  await waitFor(() => expect(run).toBeEnabled());
  return run;
}

it('opens a prefilled current-rule study from a retained manual report without starting on navigation', async () => {
  const start = mount();
  const before = JSON.stringify(studyReport);
  await screen.findByRole('button', { name: 'New analysis' });
  expect(screen.getByText('Manual regions · 1 reference')).toBeVisible();
  expect(start).not.toHaveBeenCalled();
  const run = await prepare();
  expect(screen.getByRole('checkbox', { name: 'Find single-site changes' })).toBeChecked();
  expect(screen.getByRole('textbox', { name: 'Study title' })).toHaveValue(studyReport.title);
  expect(start).not.toHaveBeenCalled();
  await userEvent.click(run);
  await waitFor(() => expect(start).toHaveBeenCalledOnce());
  expect(start.mock.calls[0]?.[1]).toMatchObject({
    expected_dataset_revision: sarDataset.revision,
    policies: [
      {
        context_id: studyReport.policies[0]!.context_id,
        direction: 'lower',
        grade_order: [],
        strong_threshold: null,
        strength_method: 'tenth_decade',
      },
    ],
    discover_single_sites: true,
    confirm_context: false,
    region_ids: [],
    core_ids: [],
  });
  expect(JSON.stringify(studyReport)).toBe(before);
});

it('reuses source-bound condition declarations without inventing or retyping them', async () => {
  const context = { ...studyContext, context: { ...studyContext.context, duration: null } };
  const declaration = {
    context_id: context.id,
    fields: { duration: '2 h' },
    source_pages: [3, 4],
    source_document_sha256: sarDataset.source_document_sha256!,
    note: '原文条件 checked',
  };
  const report = { ...studyReport, contexts: [context], context_declarations: [declaration] };
  const start = mount(report, { ...sarDataset, source_page_count: 20 });
  vi.mocked(sarStudyApi.profile).mockResolvedValue({ ...studyProfile, contexts: [context] });
  const run = await prepare();
  await userEvent.click(run);
  await waitFor(() => expect(start).toHaveBeenCalledOnce());
  expect(start.mock.calls[0]?.[1].context_declarations).toEqual([declaration]);
});

it('keeps an edited setup when the report action is used again, including a language switch', async () => {
  const start = mount();
  await prepare();
  const title = screen.getByRole('textbox', { name: 'Study title' });
  await userEvent.clear(title);
  await userEvent.type(title, 'My unsaved 原文');
  await userEvent.click(screen.getByText('Study setup'));
  expect(title).not.toBeVisible();
  await act(() => setLocale('zh-CN'));
  await userEvent.click(screen.getByRole('button', { name: '继续设置' }));
  expect(screen.getByRole('textbox', { name: '研究名称' })).toHaveValue('My unsaved 原文');
  expect(screen.getByRole('heading', { name: '完整 SAR 研究' })).toHaveFocus();
  expect(start).not.toHaveBeenCalled();
});

it.each(['stale source', 'new revision', 'another running job'])(
  'blocks unsafe reanalysis with %s',
  async (reason) => {
    const dataset = {
      ...sarDataset,
      stale: reason === 'stale source',
      revision: sarDataset.revision + (reason === 'new revision' ? 1 : 0),
    };
    const start = mount(
      studyReport,
      dataset,
      reason === 'another running job' ? [{ ...studyJob, id: 'other', status: 'running' }] : [],
    );
    const button = await screen.findByRole('button', { name: 'New analysis' });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(start).not.toHaveBeenCalled();
  },
);

it('holds the same submission identity and blocks another seed while the result is unknown', async () => {
  const start = mount();
  start.mockImplementationOnce(async (_id, body) => {
    throw new UncertainSARWrite(
      new ApiError(503, 'sar_unknown', 'Unknown outcome'),
      body.request_id,
    );
  });
  await userEvent.click(await prepare());
  const retry = await screen.findByRole('button', { name: /retry with the same request identity/ });
  expect(screen.getByRole('button', { name: 'New analysis' })).toBeDisabled();
  await userEvent.click(retry);
  await waitFor(() => expect(start).toHaveBeenCalledTimes(2));
  expect(start.mock.calls[1]?.[1]).toEqual(start.mock.calls[0]?.[1]);
});

it('shows a current-profile conflict on the confirmation step instead of a silent disabled button', async () => {
  const start = mount();
  vi.mocked(sarStudyApi.profile).mockResolvedValue({ ...studyProfile, contexts: [] });
  await userEvent.click(await screen.findByRole('button', { name: 'New analysis' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Experiment contexts changed');
  expect(screen.getByRole('button', { name: 'Run full study' })).toBeDisabled();
  expect(start).not.toHaveBeenCalled();
});
