import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { api } from '../src/api';
import { sarApi } from '../src/api/sarApi';
import { Header } from '../src/components/Header';
import { SARPage } from '../src/features/sar/SARPage';
import { SARImport } from '../src/features/sar/SARImport';
import { AnalysisForm } from '../src/features/sar/AnalysisForm';
import { CSVMappingForm } from '../src/features/sar/CSVMappingForm';
import { emptyRoute } from '../src/model/route';
import { setLocale } from '../src/i18n';
import { health, project, session } from './fixtures';
import { csvPreview, sarDataset, sarJob, sarRegion } from './sar-fixtures';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
beforeEach(() => {
  setLocale('en');
  vi.spyOn(api, 'projects').mockResolvedValue({
    items: [
      { ...project, id: 'source-A' },
      { ...project, id: 'source-B' },
    ],
  });
  vi.spyOn(sarApi, 'datasets').mockResolvedValue({ items: [], total: 0 });
});
describe('SAR review: source and completion ownership', () => {
  it('uses the known workspace route ID before project metadata is available, even over old metadata', async () => {
    const onSAR = vi.fn();
    const props = {
      view: 'workspace' as const,
      version: null,
      onUpload: vi.fn(),
      onRecent: vi.fn(),
      onNavigate: vi.fn(),
      onAnalysis: vi.fn(),
      onSAR,
      disabled: false,
      sourceProjectId: 'source-B',
    };
    const { rerender } = render(<Header {...props} project={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'SAR analysis' }));
    rerender(<Header {...props} project={{ ...project, id: 'source-A' }} />);
    await userEvent.click(screen.getByRole('button', { name: 'SAR analysis' }));
    expect(onSAR.mock.calls).toEqual([['source-B'], ['source-B']]);
    expect(props.onNavigate).not.toHaveBeenCalled();
  });
  it.each(['loading', 'error'])(
    'App keeps the source ID when jumping from a %s workspace',
    async (state) => {
      vi.spyOn(api, 'session').mockResolvedValue(session);
      vi.spyOn(api, 'health').mockResolvedValue(health);
      vi.spyOn(api, 'jobs').mockResolvedValue({ items: [] });
      vi.spyOn(api, 'project').mockImplementation(() =>
        state === 'loading'
          ? new Promise(() => {})
          : Promise.reject(new Error('metadata unavailable')),
      );
      window.location.hash = '#/projects/source-B';
      render(<App />);
      const button = screen.getByRole('button', { name: 'SAR analysis' });
      await waitFor(() => expect(button).toBeEnabled());
      await userEvent.click(button);
      await waitFor(() => expect(window.location.hash).toBe('#/sar?project=source-B'));
      expect(await screen.findByLabelText('Source project')).toHaveValue('source-B');
    },
  );
  it('does not let a late source-A snapshot steal a newer source-B SAR context', async () => {
    const pending = deferred<typeof sarDataset>();
    vi.spyOn(sarApi, 'createProject').mockReturnValue(pending.promise);
    const navigate = vi.fn();
    const routeA = { ...emptyRoute, view: 'sar' as const, projectId: 'source-A' };
    const routeB = { ...routeA, projectId: 'source-B' };
    const { rerender } = render(<SARPage active route={routeA} navigate={navigate} />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Create independent snapshot' })).toBeEnabled(),
    );
    await userEvent.type(screen.getByLabelText('Dataset title'), 'draft 原文');
    await userEvent.click(screen.getByRole('button', { name: 'Create independent snapshot' }));
    rerender(
      <SARPage
        active={false}
        route={{ ...emptyRoute, view: 'workspace', projectId: 'source-B' }}
        navigate={navigate}
      />,
    );
    rerender(<SARPage active route={routeB} navigate={navigate} />);
    await act(async () => pending.resolve({ ...sarDataset, source_project_id: 'source-A' }));
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Source project')).toHaveValue('source-B');
    expect(screen.getByLabelText('Dataset title')).toHaveValue('draft 原文');
  });
  it('does not revive a pending analysis completion after leaving and returning to the same context', async () => {
    const pending = deferred<typeof sarJob>();
    const analyse = vi.spyOn(sarApi, 'analyse').mockReturnValue(pending.promise);
    const onJob = vi.fn();
    const props = { dataset: sarDataset, region: sarRegion, busy: false, onJob };
    const { rerender } = render(<AnalysisForm {...props} active />);
    await userEvent.selectOptions(screen.getByLabelText('Activity metric'), 'metric-control');
    await userEvent.selectOptions(screen.getByLabelText('Activity direction'), 'lower');
    await userEvent.click(screen.getByRole('button', { name: 'Start reference comparison' }));
    rerender(<AnalysisForm {...props} active={false} />);
    rerender(<AnalysisForm {...props} active />);
    await act(async () => pending.resolve(sarJob));
    expect(onJob).not.toHaveBeenCalled();
    expect(analyse).toHaveBeenCalledOnce();
    expect(screen.getByLabelText('Activity direction')).toHaveValue('lower');
  });
  it('does not overwrite the import stage with a late preview from an older scope', async () => {
    const pending = deferred<typeof csvPreview>();
    vi.spyOn(sarApi, 'preview').mockReturnValue(pending.promise);
    const props = { active: true, sourceProjectId: null, onCreated: vi.fn() };
    const { rerender } = render(<SARImport {...props} scope="old-context" />);
    await userEvent.click(screen.getByRole('button', { name: 'CSV file' }));
    await userEvent.upload(
      screen.getByLabelText('Choose a CSV file'),
      new File(['id,smiles'], 'raw.csv'),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Preview on server' }));
    rerender(<SARImport {...props} scope="new-context" />);
    await act(async () => pending.resolve(csvPreview));
    expect(screen.queryByLabelText('Metric name column (optional)')).not.toBeInTheDocument();
    expect(props.onCreated).not.toHaveBeenCalled();
  });
});
describe('SAR review: concise, explicit intake', () => {
  it('hides the duplicate empty hero and picker only while the zero-dataset import is open', async () => {
    render(<SARPage active route={{ ...emptyRoute, view: 'sar' }} navigate={vi.fn()} />);
    await waitFor(() => expect(sarApi.datasets).toHaveBeenCalledOnce());
    expect(screen.queryByText('No SAR datasets yet')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('SAR datasets')).not.toBeInTheDocument();
    expect(screen.getAllByRole('heading', { name: 'Import data' })).toHaveLength(1);
    const details = screen.getByText('Method and scope').closest('details');
    expect(details).not.toHaveAttribute('open');
    await userEvent.click(screen.getByRole('button', { name: 'Import data' }));
    expect(screen.getByText('No SAR datasets yet')).toBeVisible();
    expect(screen.getByLabelText('SAR datasets')).toBeVisible();
  });
  it('blocks long mapping with two value columns, while allowing explicit wide mapping', async () => {
    const onSubmit = vi.fn();
    render(
      <CSVMappingForm
        preview={{ ...csvPreview, headers: [...csvPreview.headers, 'value2'] }}
        disabled={false}
        onSubmit={onSubmit}
      />,
    );
    await userEvent.click(screen.getByRole('checkbox', { name: 'value2' }));
    expect(screen.getByLabelText('Metric name column (optional)')).toHaveAttribute(
      'aria-invalid',
      'true',
    );
    expect(screen.getByRole('button', { name: 'Create CSV dataset' })).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
    await userEvent.selectOptions(screen.getByLabelText('Metric name column (optional)'), '');
    await userEvent.click(screen.getByRole('button', { name: 'Create CSV dataset' }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ metric_column: null, activity_columns: ['value', 'value2'] }),
    );
  });
});
