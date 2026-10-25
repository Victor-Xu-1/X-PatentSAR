import { act, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { decodeProject } from '../src/api/decoders';
import { sarApi } from '../src/api/sarApi';
import { setLocale } from '../src/i18n';
import { JobActions } from '../src/features/jobs/JobActions';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { ProjectsPage } from '../src/features/projects/ProjectsPage';
import { Metrics } from '../src/features/results/Metrics';
import { SARImport } from '../src/features/sar/SARImport';
import { job, project, projectListResource } from './fixtures';

const damaged = {
  ...project,
  id: 'unreadable-project',
  title: 'Original I-007B title',
  acceptance: { state: 'failed' as const, errors: ['Invalid saved data.'] },
  read_error: { code: 'invalid_artifact', message: 'Invalid saved data.' },
};

beforeEach(() => setLocale('en'));

it('decodes explicit per-project errors without inventing acceptance or changing legacy DTOs', () => {
  expect(decodeProject(project)).toEqual(project);
  expect(decodeProject(damaged).read_error).toEqual(damaged.read_error);
  for (const read_error of [true, {}, { code: 'invalid_artifact', message: null }])
    expect(() => decodeProject({ ...damaged, read_error })).toThrow();
  expect(() =>
    decodeProject({ ...damaged, acceptance: { state: 'accepted', errors: [] } }),
  ).toThrow();
});

it('blocks run and resume for unreadable results without inventing task state', () => {
  const create = vi.spyOn(api, 'createJob');
  render(
    <JobActions
      project={damaged}
      job={{ ...job, project_id: damaged.id, status: 'failed', can_resume: true }}
      ready
      verified
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByRole('button', { name: 'Run extraction' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Resume extraction' })).toBeDisabled();
  expect(screen.getByRole('status', { name: 'Results need repair' })).toBeVisible();
  expect(create).not.toHaveBeenCalled();
});

it('retains cancellation for an independently verified live job', () => {
  render(
    <JobActions
      project={damaged}
      job={{ ...job, project_id: damaged.id }}
      ready
      verified
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByRole('button', { name: 'Cancel task' })).toBeEnabled();
});

it('keeps independent titles and task presentation readable across languages', async () => {
  vi.spyOn(api, 'jobs').mockResolvedValue({
    items: [
      { ...job, status: 'complete' },
      { ...job, id: 'damaged-job', project_id: damaged.id, status: 'failed' },
    ],
  });
  const props = {
    projects: projectListResource([project, damaged]),
    onOpen: vi.fn(),
    ready: true,
  };
  render(<JobsPage {...props} />);
  expect(await screen.findByRole('button', { name: damaged.title })).toBeVisible();
  expect(screen.getByRole('button', { name: project.title })).toBeVisible();
  expect(screen.getByLabelText('Filter tasks by project')).toBeEnabled();
  expect(screen.getByText('Run complete')).toBeVisible();
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('status', { name: '结果数据需修复' })).toBeVisible();
  expect(screen.getByRole('button', { name: damaged.title })).toBeVisible();
});

it('keeps failed history visible and never presents unavailable summary as zero results', () => {
  render(
    <>
      <ProjectsPage
        resource={projectListResource([project, damaged])}
        onOpen={vi.fn()}
        onUpload={vi.fn()}
      />
      <Metrics project={damaged} />
    </>,
  );
  expect(screen.getByRole('button', { name: `Open ${damaged.title}` })).toBeVisible();
  expect(screen.getByText('Results need repair')).toBeVisible();
  expect(
    screen.queryByRole('region', { name: 'Actual project statistics' }),
  ).not.toBeInTheDocument();
});

it('does not snapshot an unreadable preselected SAR source', async () => {
  vi.spyOn(api, 'projects').mockResolvedValue({ items: [project, damaged] });
  const create = vi.spyOn(sarApi, 'createProject');
  render(<SARImport active sourceProjectId={damaged.id} onCreated={vi.fn()} />);
  expect(await screen.findByRole('option', { name: damaged.title })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  expect(screen.getByRole('status', { name: 'Results need repair' })).toBeVisible();
  expect(create).not.toHaveBeenCalled();
});
