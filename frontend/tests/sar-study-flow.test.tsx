import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { setLocale } from '../src/i18n';
import { emptyRoute } from '../src/model/route';
import { SARPage } from '../src/features/sar/SARPage';
import { sarDataset, studyJob, studyProfile, studyReport } from './sar-fixtures';
describe('independent default study and retained advanced mode', () => {
  it('uses explicit context → study → report → terminal soft removal without any extraction/model writes', async () => {
    setLocale('en');
    const extraction = vi.spyOn(api, 'createJob'),
      prediction = vi.spyOn(api, 'admet'),
      recognition = vi.spyOn(api, 'recognize');
    let started = false,
      removed = false;
    vi.spyOn(sarApi, 'datasets').mockResolvedValue({ items: [sarDataset], total: 1 });
    vi.spyOn(sarApi, 'dataset').mockResolvedValue(sarDataset);
    vi.spyOn(sarApi, 'jobs').mockImplementation(async () => ({
      items: started && !removed ? [studyJob] : [],
      total: started && !removed ? 1 : 0,
    }));
    vi.spyOn(sarApi, 'job').mockResolvedValue(studyJob);
    vi.spyOn(sarStudyApi, 'profile').mockResolvedValue(studyProfile);
    const study = vi.spyOn(sarStudyApi, 'start').mockImplementation(async () => {
      started = true;
      return studyJob;
    });
    vi.spyOn(sarStudyApi, 'overview').mockResolvedValue({ job: studyJob, report: studyReport });
    const remove = vi.spyOn(sarApi, 'removeJob').mockImplementation(async () => {
      removed = true;
    });
    const navigate = vi.fn();
    function Harness() {
      const [route, setRoute] = useState({
        ...emptyRoute,
        view: 'sar' as const,
        projectId: 'source 原文',
        sarDatasetId: sarDataset.id,
      });
      return (
        <SARPage
          active
          route={route}
          navigate={(next) => {
            navigate(next);
            setRoute(next as typeof route);
          }}
        />
      );
    }
    render(<Harness />);
    await screen.findByRole('group', { name: 'Choose activity measurements · 0/1' });
    expect(study).not.toHaveBeenCalled();
    const advanced = screen.getByText('Single-reference comparison (advanced)').closest('details')!;
    expect(advanced).not.toHaveAttribute('open');
    await userEvent.click(screen.getByRole('checkbox', { name: /IC50 原文.*raw assay/ }));
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Activity direction' }),
      'lower',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await userEvent.click(screen.getByRole('button', { name: 'Run full study' }));
    expect(await screen.findByRole('button', { name: 'Overview' })).toBeVisible();
    expect(navigate).toHaveBeenCalledWith(
      expect.objectContaining({
        view: 'sar',
        projectId: 'source 原文',
        sarDatasetId: sarDataset.id,
        sarJobId: studyJob.id,
      }),
    );
    expect(
      screen
        .getByRole('button', { name: 'Overview' })
        .closest('section')!
        .compareDocumentPosition(screen.getByText('Study setup').closest('details')!) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await userEvent.click(screen.getByText('Study task history'));
    await userEvent.click(screen.getByRole('button', { name: 'Remove SAR job' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm soft removal' }));
    await waitFor(() => expect(remove).toHaveBeenCalledExactlyOnceWith(studyJob.id));
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Overview' })).not.toBeInTheDocument(),
    );
    expect(navigate.mock.calls.at(-1)?.[0]).toMatchObject({ sarDatasetId: sarDataset.id });
    expect(navigate.mock.calls.at(-1)?.[0]).not.toHaveProperty('sarJobId');
    for (const action of [extraction, prediction, recognition])
      expect(action).not.toHaveBeenCalled();
    expect(study).toHaveBeenCalledOnce();
  });
});
