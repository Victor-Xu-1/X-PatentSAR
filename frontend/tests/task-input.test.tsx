import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { NewTaskPage } from '../src/features/tasks/NewTaskPage';
import { job, project } from './fixtures';

async function selectPdf(name = 'WO2026156070.pdf', content = '%PDF-1.7\ncontract') {
  await userEvent.upload(
    screen.getByLabelText('原始专利 PDF 文件'),
    new File([content], name, { type: 'application/pdf' }),
  );
}
async function advanced() {
  await userEvent.click(screen.getByText('高级选项'));
}
const props = { ready: true, connected: true, onCreated: vi.fn(), onOpen: vi.fn() };

describe('single PDF task input with two-stage recovery', () => {
  it('has one file input and primary action, with all optional fields tucked away', () => {
    render(<NewTaskPage {...props} />);
    expect(screen.getByLabelText('原始专利 PDF 文件')).toHaveFocus();
    expect(screen.getByLabelText('项目名称（可选）')).not.toBeVisible();
    expect(screen.getByLabelText('专利标识（可选）')).not.toBeVisible();
    expect(screen.getByLabelText('任务说明')).not.toBeVisible();
    expect(screen.getByRole('button', { name: '开始提取' })).toBeDisabled();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  });
  it('derives a title from the filename and always starts one durable job after upload', async () => {
    const upload = vi.spyOn(api, 'upload').mockResolvedValue(project);
    const create = vi.spyOn(api, 'createJob').mockResolvedValue(job);
    const done = vi.fn();
    render(<NewTaskPage {...props} onCreated={done} />);
    await selectPdf();
    await userEvent.click(screen.getByRole('button', { name: '开始提取' }));
    await waitFor(() => expect(done).toHaveBeenCalledExactlyOnceWith(project));
    expect(upload).toHaveBeenCalledWith(expect.any(File), 'WO2026156070', '');
    expect(create).toHaveBeenCalledExactlyOnceWith(project.id, null, {
      include_intermediates: false,
      force: false,
      task_note: '',
    });
    expect(upload.mock.invocationCallOrder[0]).toBeLessThan(create.mock.invocationCallOrder[0]!);
  });
  it('keeps optional metadata and real job flags editable and wired to the existing API', async () => {
    const upload = vi.spyOn(api, 'upload').mockResolvedValue(project);
    const create = vi.spyOn(api, 'createJob').mockResolvedValue(job);
    render(<NewTaskPage {...props} />);
    await selectPdf();
    await advanced();
    await userEvent.type(screen.getByLabelText('项目名称（可选）'), '  复核专利  ');
    await userEvent.type(screen.getByLabelText('专利标识（可选）'), 'wo2026/156070');
    await userEvent.type(screen.getByLabelText('任务说明'), '需复核来源');
    await userEvent.click(screen.getByLabelText('包含中间体'));
    await userEvent.click(screen.getByLabelText('强制重算'));
    await userEvent.click(screen.getByRole('button', { name: '开始提取' }));
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(upload).toHaveBeenCalledWith(expect.any(File), '复核专利', 'WO2026156070');
    expect(create).toHaveBeenCalledWith(project.id, null, {
      include_intermediates: true,
      force: true,
      task_note: '需复核来源',
    });
  });
  it('rejects invalid patent metadata before either write and preserves editable input', async () => {
    const upload = vi.spyOn(api, 'upload');
    const create = vi.spyOn(api, 'createJob');
    render(<NewTaskPage {...props} />);
    await selectPdf();
    await advanced();
    await userEvent.type(screen.getByLabelText('专利标识（可选）'), 'US/2026');
    await userEvent.click(screen.getByRole('button', { name: '开始提取' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('标识');
    expect(upload).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByLabelText('专利标识（可选）')).toBeEnabled();
  });
  it('rejects a renamed non-PDF before upload and does not manufacture a project', async () => {
    const upload = vi.spyOn(api, 'upload');
    const create = vi.spyOn(api, 'createJob');
    render(<NewTaskPage {...props} />);
    await selectPdf('bad.pdf', 'not a PDF');
    await userEvent.click(screen.getByRole('button', { name: '开始提取' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('文件头');
    expect(upload).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByLabelText('原始专利 PDF 文件')).toBeEnabled();
  });
  it('keeps parse failures explicit without starting a job or losing the selected file', async () => {
    vi.spyOn(api, 'upload').mockRejectedValue(
      new ApiError(422, 'invalid_pdf', '服务端 PDF 解析拒绝'),
    );
    const create = vi.spyOn(api, 'createJob');
    render(<NewTaskPage {...props} />);
    await selectPdf();
    await userEvent.click(screen.getByRole('button', { name: '开始提取' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('解析拒绝');
    expect(screen.queryByText(/PDF 已保存/)).not.toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByText('WO2026156070.pdf')).toBeVisible();
    expect(screen.getByRole('button', { name: '开始提取' })).toBeEnabled();
  });
  it('retains a successfully uploaded project and retries the job without another upload', async () => {
    const upload = vi.spyOn(api, 'upload').mockResolvedValue(project);
    const create = vi
      .spyOn(api, 'createJob')
      .mockRejectedValueOnce(new ApiError(409, 'busy', '队列繁忙'))
      .mockResolvedValueOnce(job);
    const done = vi.fn();
    const open = vi.fn();
    render(<NewTaskPage {...props} onCreated={done} onOpen={open} />);
    await selectPdf();
    await userEvent.click(screen.getByRole('button', { name: '开始提取' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('队列繁忙');
    expect(screen.getByText(/PDF 已保存/)).toBeVisible();
    expect(screen.getByLabelText('原始专利 PDF 文件')).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '打开已保存文件' }));
    expect(open).toHaveBeenCalledExactlyOnceWith(project.id);
    await userEvent.click(screen.getByRole('button', { name: '重试启动' }));
    await waitFor(() => expect(done).toHaveBeenCalledExactlyOnceWith(project));
    expect(upload).toHaveBeenCalledOnce();
    expect(create).toHaveBeenCalledTimes(2);
  });
  it('checks unknown job writes before recovery and never blindly resubmits', async () => {
    vi.spyOn(api, 'upload').mockResolvedValue(project);
    const create = vi
      .spyOn(api, 'createJob')
      .mockRejectedValue(new ApiError(0, 'timeout', '结果未知', true));
    const check = vi.spyOn(api, 'jobs').mockResolvedValue({ items: [job] });
    const done = vi.fn();
    render(<NewTaskPage {...props} onCreated={done} />);
    await selectPdf();
    await userEvent.click(screen.getByRole('button', { name: '开始提取' }));
    await screen.findByRole('alert');
    expect(screen.queryByRole('button', { name: '重试启动' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '检查任务状态' }));
    await waitFor(() => expect(done).toHaveBeenCalledExactlyOnceWith(project));
    expect(check).toHaveBeenCalledWith(project.id, expect.any(AbortSignal));
    expect(create).toHaveBeenCalledOnce();
  });
  it('requires a successful empty job check before allowing an explicit retry', async () => {
    const upload = vi.spyOn(api, 'upload').mockResolvedValue(project);
    const create = vi
      .spyOn(api, 'createJob')
      .mockRejectedValueOnce(new ApiError(0, 'timeout', '结果未知', true))
      .mockResolvedValueOnce(job);
    vi.spyOn(api, 'jobs').mockResolvedValue({ items: [] });
    render(<NewTaskPage {...props} />);
    await selectPdf();
    await userEvent.click(screen.getByRole('button', { name: '开始提取' }));
    await screen.findByRole('alert');
    await userEvent.click(screen.getByRole('button', { name: '检查任务状态' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('未查到任务');
    expect(create).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole('button', { name: '重试启动' }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    expect(upload).toHaveBeenCalledOnce();
  });
  it('blocks replay after an unknown upload and points to recent files for verification', async () => {
    const upload = vi
      .spyOn(api, 'upload')
      .mockRejectedValue(new ApiError(0, 'timeout', '结果未知', true));
    const create = vi.spyOn(api, 'createJob');
    render(<NewTaskPage {...props} />);
    await selectPdf();
    await userEvent.click(screen.getByRole('button', { name: '开始提取' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('link', { name: '最近文件' })).toHaveAttribute('href', '#/projects');
    expect(screen.queryByRole('button', { name: '开始提取' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('原始专利 PDF 文件')).toBeDisabled();
    expect(upload).toHaveBeenCalledOnce();
    expect(create).not.toHaveBeenCalled();
  });
  it('refuses a task when disconnected or incomplete runtime is reported, including native form submit', async () => {
    const upload = vi.spyOn(api, 'upload');
    const { rerender } = render(<NewTaskPage {...props} ready={false} />);
    await selectPdf();
    expect(screen.getByRole('button', { name: '开始提取' })).toBeDisabled();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    fireEvent.submit(document.querySelector('form')!);
    expect(upload).not.toHaveBeenCalled();
    rerender(<NewTaskPage {...props} connected={false} />);
    fireEvent.submit(document.querySelector('form')!);
    expect(upload).not.toHaveBeenCalled();
  });
  it('locks inputs while uploading and rejects simultaneous form submissions', async () => {
    let complete!: (value: typeof project) => void;
    const upload = vi.spyOn(api, 'upload').mockReturnValue(
      new Promise((resolve) => {
        complete = resolve;
      }),
    );
    const create = vi.spyOn(api, 'createJob').mockResolvedValue(job);
    render(<NewTaskPage {...props} />);
    await selectPdf();
    await userEvent.click(screen.getByRole('button', { name: '开始提取' }));
    expect(await screen.findByRole('button', { name: '正在上传…' })).toBeDisabled();
    expect(screen.getByLabelText('原始专利 PDF 文件')).toBeDisabled();
    fireEvent.submit(document.querySelector('form')!);
    expect(upload).toHaveBeenCalledOnce();
    complete(project);
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
  });
});
