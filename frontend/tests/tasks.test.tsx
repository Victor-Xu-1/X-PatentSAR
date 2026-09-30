import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { NewTaskPage } from '../src/features/tasks/NewTaskPage';
import { ApiError } from '../src/api/errors';
import { job, project } from './fixtures';

async function fillTask() {
  await userEvent.type(screen.getByLabelText('项目名称'), '完整任务');
  await userEvent.upload(
    screen.getByLabelText('原始专利 PDF 文件'),
    new File(['%PDF-1.7\ncontract'], 'source.pdf', { type: 'application/pdf' }),
  );
}

describe('one task input workflow with durable two-stage recovery', () => {
  it('rejects invalid optional patent metadata before upload and retains editable input', async () => {
    const upload = vi.spyOn(api, 'upload');
    render(<NewTaskPage ready connected onCreated={vi.fn()} onOpen={vi.fn()} />);
    await fillTask();
    await userEvent.type(screen.getByLabelText('专利标识（可选）'), 'US/2026');
    await userEvent.click(screen.getByRole('button', { name: '创建项目并启动完整提取' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('标识');
    expect(upload).not.toHaveBeenCalled();
    expect(screen.getByLabelText('专利标识（可选）')).toBeEnabled();
  });
  it('makes upload failures explicit without manufacturing a project or starting a job', async () => {
    vi.spyOn(api, 'upload').mockRejectedValue(
      new ApiError(422, 'invalid_pdf', '服务端 PDF 解析拒绝'),
    );
    const create = vi.spyOn(api, 'createJob');
    render(<NewTaskPage ready connected onCreated={vi.fn()} onOpen={vi.fn()} />);
    await fillTask();
    await userEvent.click(screen.getByRole('button', { name: '创建项目并启动完整提取' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('解析拒绝');
    expect(screen.queryByText(/项目已建立/)).not.toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '创建项目并启动完整提取' })).toBeEnabled();
  });
  it('defaults to full extraction, passes metadata and job options only after upload', async () => {
    const upload = vi.spyOn(api, 'upload').mockResolvedValue(project);
    const create = vi.spyOn(api, 'createJob').mockResolvedValue(job);
    const done = vi.fn();
    render(<NewTaskPage ready connected onCreated={done} onOpen={vi.fn()} />);
    expect(screen.getByLabelText(/完整提取/)).toBeChecked();
    await fillTask();
    await userEvent.type(screen.getByLabelText('专利标识（可选）'), 'wo2026/156070');
    await userEvent.type(screen.getByLabelText('任务说明（运营记录）'), '需复核来源');
    await userEvent.click(screen.getByLabelText('包含中间体'));
    await userEvent.click(screen.getByLabelText('强制重算'));
    await userEvent.click(screen.getByRole('button', { name: '创建项目并启动完整提取' }));
    await waitFor(() => expect(done).toHaveBeenCalledWith(project));
    expect(upload).toHaveBeenCalledWith(expect.any(File), '完整任务', 'WO2026156070');
    expect(create).toHaveBeenCalledWith(project.id, null, {
      include_intermediates: true,
      force: true,
      task_note: '需复核来源',
    });
    expect(upload.mock.invocationCallOrder[0]).toBeLessThan(create.mock.invocationCallOrder[0]!);
  });

  it('create-only disables job options and never pretends the note was saved', async () => {
    vi.spyOn(api, 'upload').mockResolvedValue(project);
    const create = vi.spyOn(api, 'createJob');
    const done = vi.fn();
    render(<NewTaskPage ready connected onCreated={done} onOpen={vi.fn()} />);
    await fillTask();
    await userEvent.type(screen.getByLabelText('任务说明（运营记录）'), '不应保存');
    await userEvent.click(screen.getByLabelText(/仅建立项目/));
    expect(screen.getByLabelText('包含中间体')).toBeDisabled();
    expect(screen.getByLabelText('强制重算')).toBeDisabled();
    expect(screen.getByLabelText('任务说明（运营记录）')).toBeDisabled();
    expect(screen.getByText(/不会保存到项目/)).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '仅上传并建立项目' }));
    await waitFor(() => expect(done).toHaveBeenCalledWith(project));
    expect(create).not.toHaveBeenCalled();
  });

  it('retains an uploaded project when job creation fails and retries without another upload', async () => {
    const upload = vi.spyOn(api, 'upload').mockResolvedValue(project);
    const create = vi
      .spyOn(api, 'createJob')
      .mockRejectedValueOnce(new ApiError(409, 'busy', '队列繁忙'))
      .mockResolvedValueOnce(job);
    const done = vi.fn();
    render(<NewTaskPage ready connected onCreated={done} onOpen={vi.fn()} />);
    await fillTask();
    await userEvent.click(screen.getByRole('button', { name: '创建项目并启动完整提取' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('队列繁忙');
    expect(screen.getByText(/项目已建立/)).toBeVisible();
    expect(screen.getByRole('button', { name: '打开已建立项目' })).toBeEnabled();
    expect(done).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '重试启动提取' }));
    await waitFor(() => expect(done).toHaveBeenCalledWith(project));
    expect(upload).toHaveBeenCalledOnce();
    expect(create).toHaveBeenCalledTimes(2);
  });

  it('checks job state after an uncertain start and does not blindly replay the write', async () => {
    vi.spyOn(api, 'upload').mockResolvedValue(project);
    const create = vi
      .spyOn(api, 'createJob')
      .mockRejectedValue(new ApiError(0, 'timeout', '结果未知', true));
    const check = vi.spyOn(api, 'jobs').mockResolvedValue({ items: [job] });
    const done = vi.fn();
    render(<NewTaskPage ready connected onCreated={done} onOpen={vi.fn()} />);
    await fillTask();
    await userEvent.click(screen.getByRole('button', { name: '创建项目并启动完整提取' }));
    await screen.findByRole('alert');
    expect(screen.queryByRole('button', { name: '重试启动提取' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '检查已建立项目的任务状态' }));
    await waitFor(() => expect(done).toHaveBeenCalledWith(project));
    expect(check).toHaveBeenCalledWith(project.id, expect.any(AbortSignal));
    expect(create).toHaveBeenCalledOnce();
  });

  it('rejects a renamed non-PDF before mutation and keeps the form editable', async () => {
    const upload = vi.spyOn(api, 'upload');
    render(<NewTaskPage ready connected onCreated={vi.fn()} onOpen={vi.fn()} />);
    await userEvent.type(screen.getByLabelText('项目名称'), 'invalid');
    await userEvent.upload(
      screen.getByLabelText('原始专利 PDF 文件'),
      new File(['no'], 'bad.pdf', { type: 'application/pdf' }),
    );
    await userEvent.click(screen.getByRole('button', { name: '创建项目并启动完整提取' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('文件头');
    expect(upload).not.toHaveBeenCalled();
    expect(screen.getByLabelText('项目名称')).toBeEnabled();
  });

  it('allows create-only when extraction runtime is unavailable without downgrading the default', async () => {
    render(<NewTaskPage ready={false} connected onCreated={vi.fn()} onOpen={vi.fn()} />);
    expect(screen.getByRole('button', { name: '创建项目并启动完整提取' })).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/仅建立项目/));
    expect(screen.getByRole('button', { name: '仅上传并建立项目' })).toBeEnabled();
  });
});
