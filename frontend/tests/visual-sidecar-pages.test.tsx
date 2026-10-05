import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import type { Job, Project } from '../src/api/types';
import { EnvironmentOverview } from '../src/features/environment/EnvironmentOverview';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { ProjectsPage } from '../src/features/projects/ProjectsPage';
import { NewTaskPage } from '../src/features/tasks/NewTaskPage';
import { acceptanceLabels, dateText } from '../src/model/presentation';
import { completeEnvironmentCatalog, readyEnvironmentCatalog } from './environment-setup-fixtures';
import { job, project } from './fixtures';

// Isolated component contracts only; no live API or preview sample content.
describe('bounded visual sidecar page contracts', () => {
  it('keeps the upload icon decorative, one labelled PDF input, and the not-ready guard', () => {
    const { container } = render(
      <NewTaskPage ready={false} connected onCreated={vi.fn()} onOpen={vi.fn()} />,
    );
    expect(container.querySelector('.upload-icon')).toHaveAttribute('aria-hidden', 'true');
    expect(container.querySelectorAll('input')).toHaveLength(1);
    expect(screen.getByLabelText('原始专利 PDF 文件')).toHaveFocus();
    expect(screen.getByRole('button', { name: '开始提取' })).toBeDisabled();
    expect(screen.getByRole('link', { name: '环境管理' })).toHaveAttribute('href', '#/settings');
    expect(screen.queryByText('高级选项')).not.toBeInTheDocument();
  });

  it('shows original project acceptance and update dates without inventing job status', async () => {
    const files: Project[] = (['accepted', 'failed', 'historical', 'not_run'] as const).map(
      (state, index) => ({
        ...project,
        id: `file-${index}`,
        title: `来源文件-${index}`,
        acceptance: { state, errors: [] },
        pdf: { ...project.pdf, available: index !== 2 },
      }),
    );
    const onOpen = vi.fn();
    const readJobs = vi.spyOn(api, 'jobs');
    const { container } = render(
      <ProjectsPage
        resource={{ data: { items: files }, loading: false, error: null, reload: vi.fn() }}
        onOpen={onOpen}
        onUpload={vi.fn()}
      />,
    );
    expect(screen.getAllByRole('list', { name: '最近专利文件' })).toHaveLength(1);
    for (const file of files) {
      const button = screen.getByRole('button', { name: `打开 ${file.title}` });
      expect(button).toHaveTextContent(acceptanceLabels[file.acceptance.state]);
      expect(button).toHaveTextContent(
        file.pdf.available ? `${file.pdf.page_count} 页` : '原文未提供',
      );
      expect(button.querySelector('time')).toHaveAttribute('dateTime', file.updated_at);
      expect(button.querySelector('time')).toHaveTextContent(dateText(file.updated_at));
      expect(button.querySelector('.recent-file-icon')).toHaveAttribute('aria-hidden', 'true');
      expect(button.querySelector('.recent-file-chevron')).toHaveAttribute('aria-hidden', 'true');
    }
    expect(container.querySelector('[class*="job-"]')).toBeNull();
    expect(readJobs).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: `打开 ${files[2]!.title}` }));
    expect(onOpen).toHaveBeenCalledExactlyOnceWith(files[2]!.id);
  });

  it('discloses existing stages and internal job IDs only inside native task details', async () => {
    const observed: Job = {
      ...job,
      stages: job.stages.map((stage) => ({
        ...stage,
        progress:
          stage.name === 'classify'
            ? {
                completed: 4,
                total: 11,
                cache_hits: 1,
                failures: 0,
                device: 'cpu',
                peak_rss_mb: 200,
              }
            : null,
      })),
    };
    vi.spyOn(api, 'jobs').mockResolvedValue({ items: [observed] });
    vi.spyOn(api, 'job').mockResolvedValue(observed);
    const onOpen = vi.fn();
    render(<JobsPage projects={[project]} ready onOpen={onOpen} />);
    await screen.findByRole('button', { name: project.title });
    const summary = screen.getByLabelText('提取阶段详情');
    expect(summary).toHaveTextContent('任务详情');
    expect(summary.parentElement?.tagName).toBe('DETAILS');
    expect(summary.parentElement).not.toHaveAttribute('open');
    const stages = screen.getByRole('list', { name: '真实提取流水线阶段', hidden: true });
    const identifier = screen.getByText(`任务 ${job.id}`);
    expect(stages).not.toBeVisible();
    expect(identifier).not.toBeVisible();
    expect(screen.getByText('运行中')).toBeVisible();
    expect(screen.getByRole('button', { name: '取消任务' })).toBeEnabled();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    fireEvent.click(summary);
    expect(stages).toBeVisible();
    expect(identifier).toBeVisible();
    expect(within(stages).getByText('文档分类')).toBeVisible();
    expect(within(stages).getByText(/4 \/ 11/)).toBeVisible();
    expect(screen.queryByText(/\d+%|预计完成/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: project.title }));
    expect(onOpen).toHaveBeenCalledExactlyOnceWith(project.id);
    fireEvent.click(summary);
    expect(identifier).not.toBeVisible();
  });

  it.each([
    { label: 'not-ready runtime', projects: [project], ready: false },
    {
      label: 'unavailable original',
      projects: [{ ...project, pdf: { ...project.pdf, available: false } }],
      ready: true,
    },
    { label: 'missing project metadata', projects: [], ready: true },
  ])('retains run and resume guards for $label', async ({ projects, ready }) => {
    const stopped: Job = { ...job, status: 'failed', can_resume: true };
    vi.spyOn(api, 'jobs').mockResolvedValue({ items: [stopped] });
    vi.spyOn(api, 'job').mockResolvedValue(stopped);
    const create = vi.spyOn(api, 'createJob');
    render(<JobsPage projects={projects} ready={ready} onOpen={vi.fn()} />);
    expect(await screen.findByRole('button', { name: '恢复任务' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '运行提取' })).toBeDisabled();
    expect(screen.getByText('运行失败')).toBeVisible();
    expect(screen.getByText(`任务 ${job.id}`)).not.toBeVisible();
    if (!projects.length) {
      expect(screen.getByRole('button', { name: '打开关联文件' })).toBeVisible();
      expect(screen.queryByText(job.project_id)).not.toBeInTheDocument();
    }
    expect(create).not.toHaveBeenCalled();
  });

  it('renders one environment state and preserves explicit complete-plan inspection', async () => {
    const catalog = readyEnvironmentCatalog();
    const onSetup = vi.fn();
    const onInspect = vi.fn();
    const onDetails = vi.fn();
    const { container } = render(
      <EnvironmentOverview
        catalog={catalog}
        disabled={false}
        onSetup={onSetup}
        onInspect={onInspect}
        onDetails={onDetails}
      />,
    );
    expect(screen.getAllByRole('region', { name: '完整运行环境' })).toHaveLength(1);
    expect(screen.getByText('已就绪 6/6')).toBeVisible();
    expect(container.querySelectorAll('.environment-overview-icon.is-ready')).toHaveLength(1);
    expect(screen.getByRole('button', { name: '环境已就绪' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '一键部署全部环境' })).not.toBeInTheDocument();
    expect(onSetup).not.toHaveBeenCalled();
    expect(onInspect).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '环境详情' }));
    expect(onDetails).toHaveBeenCalledOnce();
    expect(onInspect).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '重新检测' }));
    expect(onInspect).toHaveBeenCalledExactlyOnceWith(catalog.setup_component_ids);
    expect(onSetup).not.toHaveBeenCalled();
  });

  it('keeps invalid complete-plan metadata fail-closed despite ready-looking components', () => {
    const catalog = { ...readyEnvironmentCatalog(), setup_component_ids: [] };
    const onSetup = vi.fn();
    const onInspect = vi.fn();
    const { container } = render(
      <EnvironmentOverview
        catalog={catalog}
        disabled={false}
        onSetup={onSetup}
        onInspect={onInspect}
        onDetails={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: '一键部署全部环境' })).toBeDisabled();
    expect(screen.getByText(/服务端未提供有效的完整部署计划/)).toBeVisible();
    expect(container.querySelector('.environment-overview-icon.is-ready')).toBeNull();
    expect(screen.queryByRole('button', { name: '环境已就绪' })).not.toBeInTheDocument();
    expect(onSetup).not.toHaveBeenCalled();
    expect(onInspect).not.toHaveBeenCalled();
  });

  it('keeps unavailable and active-operation overview actions disabled without extra variants', () => {
    const onSetup = vi.fn();
    const onInspect = vi.fn();
    render(
      <EnvironmentOverview
        catalog={completeEnvironmentCatalog()}
        disabled
        onSetup={onSetup}
        onInspect={onInspect}
        onDetails={vi.fn()}
      />,
    );
    expect(screen.getByText('已就绪 0/6')).toBeVisible();
    expect(screen.getAllByRole('region', { name: '完整运行环境' })).toHaveLength(1);
    expect(screen.getByRole('button', { name: '一键部署全部环境' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '检测全部组件' })).toBeDisabled();
    expect(onSetup).not.toHaveBeenCalled();
    expect(onInspect).not.toHaveBeenCalled();
  });
});
