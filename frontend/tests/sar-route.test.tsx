import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { api } from '../src/api';
import { sarApi } from '../src/api/sarApi';
import { Header } from '../src/components/Header';
import { SARPage } from '../src/features/sar/SARPage';
import { emptyRoute, parseRoute, routeHash } from '../src/model/route';
import { setLocale } from '../src/i18n';
import { health, project, session } from './fixtures';
import { sarDataset } from './sar-fixtures';
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'datasets').mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(api, 'projects').mockResolvedValue({ items: [project] });
});
describe('independent refreshable SAR route', () => {
  it('round-trips source project, dataset and job identities without workspace layout side effects', () => {
    const route = {
      ...emptyRoute,
      view: 'sar' as const,
      projectId: 'source / 中文',
      sarDatasetId: 'dataset / 中文',
      sarJobId: 'job / 中文',
    };
    expect(parseRoute(routeHash(route))).toEqual(route);
    expect(routeHash(route)).toMatch(/^#\/sar\?project=/);
    expect(parseRoute('#/sar?job=orphan&tab=annotations&page=8&fullscreen=1')).toEqual({
      ...emptyRoute,
      view: 'sar',
    });
    expect(parseRoute('#/sar?project=%00&dataset=normal').projectId).toBeNull();
    expect(parseRoute('#/sar?dataset=' + 'x'.repeat(201)).sarDatasetId).toBeUndefined();
  });
  it('provides one direct SAR entry in global navigation and preserves the current source project', async () => {
    const onSAR = vi.fn();
    const onNavigate = vi.fn();
    const { rerender } = render(
      <Header
        view="workspace"
        project={project}
        version="0.1.5"
        onUpload={vi.fn()}
        onRecent={vi.fn()}
        onAnalysis={vi.fn()}
        onNavigate={onNavigate}
        onSAR={onSAR}
        disabled={false}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'SAR analysis' }));
    expect(onSAR).toHaveBeenCalledExactlyOnceWith(project.id);
    expect(onNavigate).not.toHaveBeenCalled();
    rerender(
      <Header
        view="sar"
        project={null}
        version="0.1.5"
        onUpload={vi.fn()}
        onRecent={vi.fn()}
        onAnalysis={vi.fn()}
        onNavigate={onNavigate}
        disabled={false}
      />,
    );
    expect(screen.getByRole('button', { name: 'SAR analysis' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await userEvent.click(screen.getByRole('button', { name: 'SAR analysis' }));
    expect(onNavigate).toHaveBeenCalledWith('sar');
  });
  it('opens the App SAR route with read-only datasets/projects, never the extraction or analysis workflow', async () => {
    vi.spyOn(api, 'session').mockResolvedValue(session);
    vi.spyOn(api, 'health').mockResolvedValue(health);
    const originalJob = vi.spyOn(api, 'createJob');
    const originalAnalysis = vi.spyOn(api, 'admet');
    const create = vi.spyOn(sarApi, 'createProject');
    const csv = vi.spyOn(sarApi, 'createCSV');
    const analyse = vi.spyOn(sarApi, 'analyse');
    window.location.hash = '#/sar';
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'SAR analysis', level: 1 })).toBeVisible();
    expect(screen.getByRole('button', { name: 'SAR analysis' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.queryByRole('button', { name: 'Start extraction' })).not.toBeInTheDocument();
    for (const action of [originalJob, originalAnalysis, create, csv, analyse])
      expect(action).not.toHaveBeenCalled();
  });
  it('does not read or poll while inactive, and keeps import drafts across locale changes', async () => {
    const datasets = vi
      .spyOn(sarApi, 'datasets')
      .mockResolvedValue({ items: [sarDataset], total: 1 });
    const props = {
      route: { ...emptyRoute, view: 'sar' as const, projectId: project.id },
      navigate: vi.fn(),
    };
    const { rerender } = render(<SARPage {...props} active={false} />);
    expect(datasets).not.toHaveBeenCalled();
    expect(api.projects).not.toHaveBeenCalled();
    rerender(<SARPage {...props} active />);
    const title = await screen.findByLabelText('Dataset title');
    await userEvent.type(title, 'draft untouched');
    const before = datasets.mock.calls.length;
    await act(() => setLocale('zh-CN'));
    expect(screen.getByLabelText('数据集名称')).toBe(title);
    expect(title).toHaveValue('draft untouched');
    expect(datasets.mock.calls.length).toBe(before);
    rerender(<SARPage {...props} active={false} />);
    expect(datasets.mock.calls[0]?.[0].aborted).toBe(true);
  });
});
