import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { Header } from '../src/components/Header';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { NewTaskPage } from '../src/features/tasks/NewTaskPage';
import { environmentCatalog, environmentOperation } from './environment-fixtures';
import { health, job, project } from './fixtures';

describe('minimal secondary page presentation without changing workflows', () => {
  it('does not duplicate a page title in the header, preserving brand and version', async () => {
    render(
      <Header
        view="settings"
        project={null}
        version="0.1.0"
        onUpload={vi.fn()}
        onRecent={vi.fn()}
        onNavigate={vi.fn()}
        onAnalysis={vi.fn()}
        disabled={false}
      />,
    );
    expect(document.querySelector('.document-title')).toBeNull();
    expect(screen.getByRole('link', { name: 'X-PatentSAR · 上传 PDF' })).toHaveTextContent(
      'X-PatentSAR',
    );
    await userEvent.click(screen.getByLabelText('更多'));
    expect(screen.getByText('v0.1.0')).toBeVisible();
    expect(screen.getByRole('button', { name: '环境管理' })).toBeVisible();
  });

  it('leaves one PDF entry and one action, with optional controls disclosed separately', async () => {
    render(<NewTaskPage ready connected onCreated={vi.fn()} onOpen={vi.fn()} />);
    expect(screen.getByRole('heading', { level: 1, name: '上传专利 PDF' })).toBeVisible();
    expect(document.querySelector('.task-heading p')).toBeNull();
    expect(document.querySelector('.eyebrow')).toBeNull();
    expect(screen.getByLabelText('原始专利 PDF 文件')).toBeVisible();
    expect(screen.getByRole('button', { name: '开始提取' })).toBeDisabled();
    expect(screen.getByLabelText('包含中间体')).not.toBeVisible();
    await userEvent.click(screen.getByText('高级选项'));
    expect(screen.getByLabelText('包含中间体')).toBeVisible();
  });

  it('discloses actual job stages on demand while retaining project and task identifiers', async () => {
    const complete = {
      ...job,
      status: 'complete' as const,
      stages: job.stages.map((stage) => ({ ...stage, status: 'ok' as const })),
    };
    vi.spyOn(api, 'jobs').mockResolvedValue({ items: [complete] });
    vi.spyOn(api, 'job').mockResolvedValue(complete);
    const onOpen = vi.fn();
    render(<JobsPage projects={[project]} ready onOpen={onOpen} />);
    expect(await screen.findByText('任务 ' + job.id)).toHaveAttribute('title', job.id);
    expect(document.querySelector('.eyebrow')).toBeNull();
    expect(screen.getByRole('heading', { level: 1, name: '任务记录' })).toBeVisible();
    const stages = screen.getByRole('list', { name: '真实提取流水线阶段', hidden: true });
    expect(stages).not.toBeVisible();
    fireEvent.click(screen.getByLabelText('提取阶段详情'));
    expect(stages).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: project.title }));
    expect(onOpen).toHaveBeenCalledExactlyOnceWith(project.id);
  });

  it('keeps environmental safety on demand without starting installation', async () => {
    sessionStorage.clear();
    vi.spyOn(api, 'environments').mockResolvedValue(environmentCatalog);
    vi.spyOn(api, 'environmentOperation').mockResolvedValue(environmentOperation);
    vi.spyOn(api, 'runtime').mockResolvedValue({
      product: health.product,
      storage: { state_root: '/srv/wsl/state', platform: 'linux' },
      interpreters: [],
      capabilities: health.capabilities,
    });
    const install = vi.spyOn(api, 'createEnvironmentOperation');
    render(<EnvironmentPage product={health.product} operationId={null} onOperation={vi.fn()} />);
    await screen.findByRole('heading', { name: '组件库' });
    expect(document.querySelector('.page-header p')).toBeNull();
    expect(document.querySelector('.eyebrow')).toBeNull();
    const notice = screen.getByText(/只有明确确认后才会安装/);
    expect(notice).not.toBeVisible();
    await userEvent.click(screen.getByText('运行与安装说明'));
    expect(notice).toBeVisible();
    expect(screen.getByText('X-PatentSAR · v0.1.0')).toBeVisible();
    expect(install).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '安装组合 推荐基础组合' })).toBeEnabled(),
    );
  });
});
