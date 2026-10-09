import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { setLocale } from '../src/i18n';
import { StudySetup } from '../src/features/sar/study/StudySetup';
import { StudyResults } from '../src/features/sar/study/StudyResults';
import {
  sarDataset,
  sarDrawing,
  sarMolecule,
  studyJob,
  studyProfile,
  studyReport,
} from './sar-fixtures';

beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue(studyProfile);
  vi.spyOn(sarStudyApi, 'start').mockResolvedValue(studyJob);
  vi.spyOn(sarApi, 'job').mockResolvedValue(studyJob);
  vi.spyOn(sarStudyApi, 'overview').mockResolvedValue({ job: studyJob, report: studyReport });
  vi.spyOn(sarStudyApi, 'drawing').mockImplementation(async (_job, _kind, id) => ({
    id,
    svg: sarDrawing.svg,
  }));
});

it('guides activity selection before analysis; back/locale preserve drafts and do not issue a write', async () => {
  render(<StudySetup dataset={sarDataset} active disabled={false} scope="owned" onJob={vi.fn()} />);
  const guide = screen.getByRole('list', { name: 'Analysis steps' });
  expect(guide.querySelector('[aria-current="step"]')).toHaveTextContent('2Activity');
  expect(screen.queryByRole('button', { name: 'Run full study' })).not.toBeInTheDocument();
  const selected = await screen.findByRole('checkbox', { name: /IC50 原文.*raw assay/ });
  await userEvent.click(selected);
  await userEvent.selectOptions(screen.getByLabelText('Activity direction'), 'lower');
  await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
  expect(guide.querySelector('[aria-current="step"]')).toHaveTextContent('3Analyze');
  expect(screen.getByRole('heading', { name: 'Full SAR study' })).toHaveFocus();
  const title = screen.getByLabelText('Study title');
  await userEvent.clear(title);
  await userEvent.type(title, 'source-owned draft 原文');
  await userEvent.click(screen.getByRole('button', { name: 'Back' }));
  expect(selected).toBeChecked();
  expect(screen.getByLabelText('Activity direction')).toHaveValue('lower');
  await act(() => setLocale('zh-CN'));
  expect(guide.querySelector('[aria-current="step"]')).toHaveTextContent('2选择活性');
  await userEvent.click(screen.getByRole('button', { name: '下一步' }));
  expect(screen.getByLabelText('研究名称')).toBe(title);
  expect(title).toHaveValue('source-owned draft 原文');
  expect(sarStudyApi.start).not.toHaveBeenCalled();
});

it('puts technical counts and provenance in one deliberate dialog, not the preview body', async () => {
  render(
    <StudyResults
      dataset={sarDataset}
      jobId={studyJob.id}
      active
      disabled={false}
      scope="owned"
      onJob={vi.fn()}
    />,
  );
  await screen.findByText(studyReport.title);
  expect(screen.queryByText('Comparisons checked')).not.toBeInTheDocument();
  expect(screen.queryByText('Candidate policy and ties')).not.toBeInTheDocument();
  const details = screen.getByRole('button', { name: 'Details' });
  await userEvent.click(details);
  const dialog = screen.getByRole('dialog', { name: 'Details' });
  expect(within(dialog).getByText('Comparisons checked')).toBeVisible();
  expect(within(dialog).getByText('Activity rules')).toBeVisible();
  // jsdom does not implement the browser's native Escape -> cancel dispatch.
  // Real Chromium exercises that keyboard path in sar-study.spec.ts.
  fireEvent(dialog, new Event('cancel', { cancelable: true }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(details).toHaveFocus();
  expect(sarStudyApi.start).not.toHaveBeenCalled();
});

it('makes candidate cards data-only, without silently removing detailed facts', async () => {
  render(
    <StudyResults
      dataset={sarDataset}
      jobId={studyJob.id}
      active
      disabled={false}
      scope="owned"
      onJob={vi.fn()}
    />,
  );
  await userEvent.click(await screen.findByRole('button', { name: 'Leads' }));
  const preview = screen.getByRole('region', { name: 'Leads' });
  expect(within(preview).getByRole('heading', { name: sarMolecule.label })).toBeVisible();
  expect(preview.querySelectorAll('.sar-lead-card details')).toHaveLength(0);
  expect(preview.querySelector('.sar-candidate-coverage')).toBeNull();
  expect(preview.querySelector('.sar-candidate-properties')).not.toBeNull();
  expect(within(preview).getByRole('button', { name: 'Source details' })).toBeVisible();
  expect(within(preview).queryByText('Pareto layer')).not.toBeInTheDocument();
});
