import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { api } from '../src/api';
import { sarApi } from '../src/api/sarApi';
import { setLocale } from '../src/i18n';
import { health, project, session } from './fixtures';
import {
  sarDataset,
  sarDrawing,
  sarInvalid,
  sarJob,
  sarMolecule,
  sarPair,
  sarRegion,
} from './sar-fixtures';

describe('complete independent SAR frontend contract flow', () => {
  it('runs explicit snapshot → reference → immutable region → metric comparison with no extraction or LLM path', async () => {
    setLocale('en');
    window.location.hash = '#/sar?project=project-control';
    vi.spyOn(api, 'session').mockResolvedValue(session);
    vi.spyOn(api, 'health').mockResolvedValue(health);
    vi.spyOn(api, 'projects').mockResolvedValue({ items: [{ ...project, id: 'project-control' }] });
    const extraction = vi.spyOn(api, 'createJob');
    const prediction = vi.spyOn(api, 'admet');
    const recognition = vi.spyOn(api, 'recognize');
    let imported = false,
      analysed = false,
      removed = false;
    vi.spyOn(sarApi, 'datasets').mockImplementation(async () => ({
      items: imported ? [sarDataset] : [],
      total: imported ? 1 : 0,
    }));
    const create = vi.spyOn(sarApi, 'createProject').mockImplementation(async () => {
      imported = true;
      return sarDataset;
    });
    vi.spyOn(sarApi, 'dataset').mockResolvedValue(sarDataset);
    vi.spyOn(sarApi, 'molecules').mockResolvedValue({
      items: [sarMolecule, sarInvalid],
      total: 3,
      page: 1,
      page_size: 50,
    });
    vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
    vi.spyOn(sarApi, 'jobs').mockImplementation(async () => ({
      items: analysed && !removed ? [sarJob] : [],
      total: analysed && !removed ? 1 : 0,
    }));
    const save = vi.spyOn(sarApi, 'saveRegion').mockResolvedValue(sarRegion);
    const analyse = vi.spyOn(sarApi, 'analyse').mockImplementation(async () => {
      analysed = true;
      return sarJob;
    });
    const remove = vi.spyOn(sarApi, 'removeJob').mockImplementation(async () => {
      removed = true;
    });
    const resume = vi.spyOn(sarApi, 'resume');
    vi.spyOn(sarApi, 'job').mockResolvedValue(sarJob);
    vi.spyOn(sarApi, 'pairs').mockResolvedValue({
      items: [sarPair],
      total: 1,
      page: 1,
      page_size: 50,
      job: sarJob,
    });
    render(<App />);
    await userEvent.click(
      await screen.findByRole('button', { name: 'Create independent snapshot' }),
    );
    expect(await screen.findByText('原文 missing')).toBeVisible();
    await userEvent.click(screen.getAllByRole('button', { name: 'Reference' })[0]!);
    const image = await screen.findByRole('img', { name: 'RDKit reference drawing' });
    fireEvent.load(image);
    await userEvent.click(screen.getByRole('button', { name: 'Atom 1 (O)' }));
    await act(() => setLocale('zh-CN'));
    expect(screen.getByRole('button', { name: '原子 1（O）' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await act(() => setLocale('en'));
    await userEvent.click(screen.getByRole('button', { name: 'Save region' }));
    await screen.findByText('Region saved · 1 attachment points');
    await userEvent.selectOptions(screen.getByLabelText('Activity metric'), 'metric-control');
    await userEvent.selectOptions(screen.getByLabelText('Activity direction'), 'lower');
    await userEvent.click(screen.getByRole('button', { name: 'Start reference comparison' }));
    expect(await screen.findByText('原文 009')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Reference source details' })).toHaveTextContent(
      sarMolecule.label,
    );
    expect(screen.getAllByText('<10 nM')).toHaveLength(2);
    await waitFor(() => expect(window.location.hash).toContain('job=job-control'));
    expect(create).toHaveBeenCalledOnce();
    expect(save).toHaveBeenCalledOnce();
    expect(analyse).toHaveBeenCalledOnce();
    expect(analyse.mock.calls[0]?.[1]).toMatchObject({
      expected_dataset_revision: 2,
      region_id: sarRegion.id,
      grade_order: [],
      confirm_context: false,
    });
    for (const original of [extraction, prediction, recognition])
      expect(original).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Remove SAR job' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm soft removal' }));
    await waitFor(() => expect(window.location.hash).not.toContain('job='));
    expect(window.location.hash).toContain('dataset=dataset-control');
    expect(screen.queryByText('原文 009')).not.toBeInTheDocument();
    expect(remove).toHaveBeenCalledExactlyOnceWith(sarJob.id);
    expect(analyse).toHaveBeenCalledOnce();
    expect(resume).not.toHaveBeenCalled();
  });
});
