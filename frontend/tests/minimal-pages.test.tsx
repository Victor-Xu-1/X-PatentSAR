import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { Header } from '../src/components/Header';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { NewTaskPage } from '../src/features/tasks/NewTaskPage';
import { environmentOperation } from './environment-fixtures';
import { completeEnvironmentCatalog } from './environment-setup-fixtures';
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
    expect(screen.getByText('v0.1.0')).toBeVisible();
    expect(screen.getByRole('button', { name: '环境管理' })).toBeVisible();
  });

  it('leaves one PDF entry and one action without an advanced-options section', () => {
    render(<NewTaskPage ready connected onCreated={vi.fn()} onOpen={vi.fn()} />);
    expect(screen.getByRole('heading', { level: 1, name: '上传专利 PDF' })).toBeVisible();
    expect(document.querySelector('.task-heading p')).toBeNull();
    expect(document.querySelector('.eyebrow')).toBeNull();
    expect(screen.getByLabelText('原始专利 PDF 文件')).toBeVisible();
    expect(screen.getByRole('button', { name: '开始提取' })).toBeDisabled();
    expect(screen.queryByText('高级选项')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('包含中间体')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('项目名称（可选）')).not.toBeInTheDocument();
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
    vi.spyOn(api, 'environments').mockResolvedValue(completeEnvironmentCatalog());
    vi.spyOn(api, 'environmentOperation').mockResolvedValue(environmentOperation);
    vi.spyOn(api, 'runtime').mockResolvedValue({
      product: health.product,
      storage: { state_root: '/srv/wsl/state', platform: 'linux' },
      interpreters: [],
      capabilities: health.capabilities,
    });
    const install = vi.spyOn(api, 'createEnvironmentOperation');
    render(<EnvironmentPage product={health.product} operationId={null} onOperation={vi.fn()} />);
    await screen.findByRole('heading', { name: '完整运行环境' });
    expect(document.querySelector('.page-header p')).toBeNull();
    expect(document.querySelector('.eyebrow')).toBeNull();
    expect(screen.queryByText('运行与安装说明')).not.toBeInTheDocument();
    expect(screen.queryByText(/操作日志|操作历史|安装位置：|目标：/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '环境详情' })).toBeVisible();
    expect(install).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '一键部署全部环境' })).toBeEnabled(),
    );
  });
});
