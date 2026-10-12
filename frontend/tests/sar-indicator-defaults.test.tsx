import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { decodeStudyProfile } from '../src/api/sarStudyDecoders';
import { setLocale } from '../src/i18n';
import { AnalysisForm } from '../src/features/sar/AnalysisForm';
import { StudySetup } from '../src/features/sar/study/StudySetup';
import {
  sarDataset,
  sarJob,
  sarRegion,
  studyContext,
  studyJob,
  studyProfile,
} from './sar-fixtures';

const lower = { direction: 'lower' as const, rule: 'potency' };
const profile = {
  ...studyProfile,
  policy_defaults: { [studyContext.id]: lower },
  metric_defaults: { [studyContext.metric_id]: lower },
};
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue(profile);
  vi.spyOn(sarStudyApi, 'start').mockResolvedValue(studyJob);
  vi.spyOn(sarApi, 'analyse').mockResolvedValue(sarJob);
});
describe('server-owned SAR indicator defaults', () => {
  it('decodes current defaults without adding them to legacy profile facts', () => {
    expect(decodeStudyProfile(profile)).toEqual(profile);
    expect(decodeStudyProfile(studyProfile)).toEqual(studyProfile);
    for (const bad of [
      { policy_defaults: { foreign: lower } },
      { metric_defaults: { foreign: lower } },
      { policy_defaults: { [studyContext.id]: { direction: 'guessed', rule: 'potency' } } },
    ])
      expect(() => decodeStudyProfile({ ...profile, ...bad })).toThrow();
  });
  it('uses a known rule after selecting activity without another direction operation or a job on entry', async () => {
    render(
      <StudySetup dataset={sarDataset} active disabled={false} scope="current" onJob={vi.fn()} />,
    );
    await userEvent.click(await screen.findByRole('checkbox', { name: /IC50 原文/ }));
    expect(screen.queryByRole('combobox', { name: 'Activity direction' })).not.toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Activity direction' })).toHaveTextContent(
      'Automatic · Lower is stronger',
    );
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
    expect(sarStudyApi.start).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await userEvent.click(screen.getByRole('button', { name: 'Run full study' }));
    await waitFor(() => expect(sarStudyApi.start).toHaveBeenCalledOnce());
    expect(vi.mocked(sarStudyApi.start).mock.calls[0]?.[1].policies[0]).toMatchObject({
      direction: 'lower',
      grade_order: [],
    });
  });
  it('needs explicit confirmation only for a rule that the server did not establish', async () => {
    vi.mocked(sarStudyApi.profile).mockResolvedValue({
      ...profile,
      policy_defaults: { [studyContext.id]: { direction: 'unknown', rule: 'unknown' } },
    });
    render(
      <StudySetup dataset={sarDataset} active disabled={false} scope="current" onJob={vi.fn()} />,
    );
    await userEvent.click(await screen.findByRole('checkbox', { name: /IC50 原文/ }));
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText('Activity direction'), 'higher');
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
  });
  it('uses the same server default for single-reference comparison and keeps the exact request contract', async () => {
    render(<AnalysisForm dataset={sarDataset} region={sarRegion} busy={false} onJob={vi.fn()} />);
    await userEvent.selectOptions(screen.getByLabelText('Activity metric'), 'metric-control');
    await screen.findByRole('status', { name: 'Activity direction' });
    expect(screen.queryByRole('combobox', { name: 'Activity direction' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Start reference comparison' }));
    await waitFor(() => expect(sarApi.analyse).toHaveBeenCalledOnce());
    expect(vi.mocked(sarApi.analyse).mock.calls[0]?.[1]).toMatchObject({
      direction: 'lower',
      grade_order: [],
      confirm_context: false,
    });
  });
  it('takes negative-log polarity from the server, not a frontend name guess', async () => {
    vi.mocked(sarStudyApi.profile).mockResolvedValue({
      ...profile,
      metric_defaults: { [studyContext.metric_id]: { direction: 'higher', rule: 'log_potency' } },
    });
    render(<AnalysisForm dataset={sarDataset} region={sarRegion} busy={false} onJob={vi.fn()} />);
    await userEvent.selectOptions(screen.getByLabelText('Activity metric'), 'metric-control');
    expect(await screen.findByRole('status', { name: 'Activity direction' })).toHaveTextContent(
      'Higher is stronger',
    );
    await act(() => setLocale('zh-CN'));
    expect(screen.getByRole('status', { name: '活性方向' })).toHaveTextContent(
      '自动 · 值越高活性越强',
    );
    expect(sarApi.analyse).not.toHaveBeenCalled();
  });
  it('retains a known draft but disables it after failed revalidation until an explicit reload', async () => {
    const props = { dataset: sarDataset, region: sarRegion, busy: false, onJob: vi.fn() };
    const { rerender } = render(<AnalysisForm {...props} active />);
    await userEvent.selectOptions(screen.getByLabelText('Activity metric'), 'metric-control');
    await screen.findByRole('status', { name: 'Activity direction' });
    rerender(<AnalysisForm {...props} active={false} />);
    vi.mocked(sarStudyApi.profile).mockRejectedValueOnce(new Error('Recorded rules unavailable'));
    rerender(<AnalysisForm {...props} active />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Recorded rules unavailable');
    expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Reload' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeEnabled(),
    );
    expect(sarApi.analyse).not.toHaveBeenCalled();
  });
});
