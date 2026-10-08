import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, client } from '../src/api';
import { ApiError } from '../src/api/errors';
import { llmApi } from '../src/api/llmApi';
import type { Job } from '../src/api/types';
import { JobActions } from '../src/features/jobs/JobActions';
import { json, project, session } from './fixtures';
import { authorizedJob, deferred, recoveryJob, recoverySettings } from './llm-recovery-fixtures';

function mount(current: Job = recoveryJob, compact = false) {
  const onChange = vi.fn();
  const view = render(
    <JobActions project={project} job={current} ready onChange={onChange} compact={compact} />,
  );
  return { ...view, onChange };
}
async function open() {
  await userEvent.click(screen.getByText('任务详情', { selector: 'summary' }));
  await userEvent.click(screen.getByRole('button', { name: '更新 API 授权' }));
  const dialog = await screen.findByRole('dialog', { name: '更新此任务的 API 授权？' });
  await waitFor(() =>
    expect(within(dialog).getByRole('button', { name: '确认更新授权' })).toBeEnabled(),
  );
  return dialog;
}

describe('explicit logical-job API reauthorization', () => {
  beforeEach(() => {
    client.resetSession();
    vi.spyOn(llmApi, 'settings').mockResolvedValue(recoverySettings);
    vi.spyOn(api, 'reauthorizeJobLLM').mockResolvedValue(authorizedJob);
    vi.spyOn(api, 'createJob').mockResolvedValue({ ...recoveryJob, status: 'queued' });
    vi.spyOn(llmApi, 'test');
  });

  it('reads the current revision before explicit consent, refreshes on success and never starts a job/model', async () => {
    const { onChange, rerender } = mount();
    expect(llmApi.settings).not.toHaveBeenCalled();
    expect(api.reauthorizeJobLLM).not.toHaveBeenCalled();
    const dialog = await open();
    expect(llmApi.settings).toHaveBeenCalledOnce();
    expect(dialog).toHaveTextContent('已保存且相同服务、模型和协议的凭据');
    expect(dialog).toHaveTextContent('不重置配额、不开始提取、不调用模型');
    expect(dialog).toHaveTextContent(recoverySettings.model);
    expect(within(dialog).queryByLabelText('API 密钥')).not.toBeInTheDocument();
    expect(api.reauthorizeJobLLM).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '继续提取' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '运行提取' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '正在提交…' })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: '确认更新授权' }));
    await waitFor(() => expect(onChange).toHaveBeenCalledOnce());
    expect(api.reauthorizeJobLLM).toHaveBeenCalledExactlyOnceWith(
      recoveryJob.id,
      recoverySettings.revision,
    );
    expect(screen.getByRole('status')).toHaveTextContent('未开始提取');
    expect(screen.getByRole('button', { name: '继续提取' })).toBeDisabled();
    rerender(<JobActions project={project} job={authorizedJob} ready onChange={onChange} />);
    expect(screen.getByRole('button', { name: '继续提取' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: '更新 API 授权' })).not.toBeInTheDocument();
    expect(api.createJob).not.toHaveBeenCalled();
    expect(llmApi.test).not.toHaveBeenCalled();
  });

  it('cancels confirmation without a POST and returns focus to the single action', async () => {
    mount();
    const dialog = await open();
    await userEvent.click(within(dialog).getByRole('button', { name: '取消' }));
    expect(dialog).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '更新 API 授权' })).toHaveFocus();
    expect(screen.getByRole('button', { name: '继续提取' })).toBeEnabled();
    expect(api.reauthorizeJobLLM).not.toHaveBeenCalled();
  });

  it('cancels an in-flight settings read and ignores its late result', async () => {
    const pending = deferred<typeof recoverySettings>();
    vi.mocked(llmApi.settings).mockReturnValue(pending.promise);
    mount();
    await userEvent.click(screen.getByText('任务详情', { selector: 'summary' }));
    await userEvent.click(screen.getByRole('button', { name: '更新 API 授权' }));
    const dialog = screen.getByRole('dialog', { name: '更新此任务的 API 授权？' });
    expect(within(dialog).getByRole('button', { name: '确认更新授权' })).toBeDisabled();
    const signal = vi.mocked(llmApi.settings).mock.calls[0]![0];
    fireEvent(dialog, new Event('cancel', { cancelable: true }));
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(recoverySettings));
    expect(dialog).not.toBeInTheDocument();
    expect(api.reauthorizeJobLLM).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '继续提取' })).toBeEnabled();
  });

  it('deduplicates reads/posts and blocks competing resume/close during a write', async () => {
    const pending = deferred<Job>();
    vi.mocked(api.reauthorizeJobLLM).mockReturnValue(pending.promise);
    const { onChange } = mount();
    const dialog = await open();
    fireEvent.click(screen.getByRole('button', { name: '更新 API 授权', hidden: true }));
    expect(llmApi.settings).toHaveBeenCalledOnce();
    const confirm = within(dialog).getByRole('button', { name: '确认更新授权' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    fireEvent.click(screen.getByRole('button', { name: '继续提取', hidden: true }));
    fireEvent(dialog, new Event('cancel', { cancelable: true }));
    expect(within(dialog).getByRole('button', { name: '取消' })).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: '关闭对话框' })).toBeDisabled();
    expect(dialog).toBeInTheDocument();
    expect(api.reauthorizeJobLLM).toHaveBeenCalledOnce();
    expect(api.createJob).not.toHaveBeenCalled();
    await act(async () => pending.resolve(authorizedJob));
    expect(onChange).toHaveBeenCalledOnce();
  });

  it.each([
    new ApiError(409, 'llm_settings_changed', 'untrusted-provider-content'),
    new ApiError(409, 'llm_authorization_changed', 'untrusted-provider-content'),
    new ApiError(0, 'network_error', 'untrusted-provider-content', true),
    new ApiError(200, 'invalid_write_response', 'untrusted-provider-content', true),
    new ApiError(503, 'provider_failure', 'untrusted-provider-content'),
    new ApiError(422, 'incompatible_profile', 'untrusted-provider-content'),
    new ApiError(404, 'not_found', 'untrusted-provider-content'),
  ])('offers only authoritative refresh after a failed/uncertain write %#', async (failure) => {
    vi.mocked(api.reauthorizeJobLLM).mockRejectedValue(failure);
    const { onChange, rerender } = mount();
    const dialog = await open();
    await userEvent.click(within(dialog).getByRole('button', { name: '确认更新授权' }));
    const alert = await within(dialog).findByRole('alert');
    expect(alert).toHaveTextContent(/刷新|核对/);
    expect(alert).not.toHaveTextContent('untrusted-provider-content');
    expect(within(dialog).queryByRole('button', { name: '确认更新授权' })).not.toBeInTheDocument();
    expect(api.reauthorizeJobLLM).toHaveBeenCalledOnce();
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole('button', { name: '取消' }));
    expect(screen.getByRole('button', { name: '继续提取' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '刷新核对任务与配置' }));
    expect(onChange).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: '继续提取' })).toBeDisabled();
    expect(api.reauthorizeJobLLM).toHaveBeenCalledOnce();
    rerender(<JobActions project={project} job={{ ...recoveryJob }} ready onChange={onChange} />);
    expect(screen.getByRole('button', { name: '继续提取' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: '更新 API 授权' }));
    await waitFor(() => expect(llmApi.settings).toHaveBeenCalledTimes(2));
    expect(api.reauthorizeJobLLM).toHaveBeenCalledOnce();
    expect(api.createJob).not.toHaveBeenCalled();
  });

  it.each([
    { ...recoveryJob, status: 'running' as const },
    { ...recoveryJob, can_resume: false },
    { ...recoveryJob, llm_recovery: { ...recoveryJob.llm_recovery!, can_reauthorize: false } },
  ])(
    'blocks confirmation if a current capability changes during the dialog %#',
    async (current) => {
      const { rerender, onChange } = mount();
      const dialog = await open();
      rerender(<JobActions project={project} job={current} ready onChange={onChange} />);
      expect(
        within(dialog).queryByRole('button', { name: '确认更新授权' }),
      ).not.toBeInTheDocument();
      expect(within(dialog).getByRole('alert')).toHaveTextContent('任务状态已改变');
      expect(api.reauthorizeJobLLM).not.toHaveBeenCalled();
    },
  );

  it.each(['disabled', 'incomplete'] as const)(
    'does not authorize an incomplete or revoked current %s configuration',
    async (status) => {
      vi.mocked(llmApi.settings).mockResolvedValue({
        ...recoverySettings,
        status,
        mode: status === 'disabled' ? 'off' : 'on-error',
        key_configured: status !== 'incomplete',
      });
      mount();
      await userEvent.click(screen.getByText('任务详情', { selector: 'summary' }));
      await userEvent.click(screen.getByRole('button', { name: '更新 API 授权' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('完整的 API 配置与外发授权');
      expect(screen.getByRole('button', { name: '确认更新授权' })).toBeDisabled();
      expect(api.reauthorizeJobLLM).not.toHaveBeenCalled();
    },
  );

  it('shows a safe read failure without enabling a write', async () => {
    vi.mocked(llmApi.settings).mockRejectedValue(new Error('synthetic-sensitive-read-error'));
    mount();
    await userEvent.click(screen.getByText('任务详情', { selector: 'summary' }));
    await userEvent.click(screen.getByRole('button', { name: '更新 API 授权' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('无法读取');
    expect(document.body.textContent).not.toContain('synthetic-sensitive-read-error');
    expect(screen.getByRole('button', { name: '确认更新授权' })).toBeDisabled();
    expect(api.reauthorizeJobLLM).not.toHaveBeenCalled();
  });

  it('rejects a successful response for another project as uncertain', async () => {
    vi.mocked(api.reauthorizeJobLLM).mockResolvedValue({
      ...authorizedJob,
      project_id: 'foreign-project',
    });
    const { onChange } = mount();
    const dialog = await open();
    await userEvent.click(within(dialog).getByRole('button', { name: '确认更新授权' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('写入结果尚未确认');
    expect(onChange).not.toHaveBeenCalled();
    expect(api.reauthorizeJobLLM).toHaveBeenCalledOnce();
  });

  it('retains the compact original-task details and guards its parent dialog while authorizing', async () => {
    mount(recoveryJob, true);
    expect(screen.queryByText('局部修复受阻')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '任务详情' }));
    const parent = screen.getByRole('dialog', { name: '任务详情' });
    expect(within(parent).getAllByRole('button', { name: '更新 API 授权' })).toHaveLength(1);
    await userEvent.click(within(parent).getByRole('button', { name: '更新 API 授权' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '确认更新授权' })).toBeEnabled());
    expect(
      within(parent).getAllByRole('button', { name: '关闭对话框', hidden: true })[0],
    ).toBeDisabled();
    fireEvent(parent, new Event('cancel', { cancelable: true }));
    expect(parent).toBeInTheDocument();
    const confirmation = screen.getByRole('dialog', { name: '更新此任务的 API 授权？' });
    await userEvent.click(within(confirmation).getByRole('button', { name: '取消' }));
    expect(api.reauthorizeJobLLM).not.toHaveBeenCalled();
  });
});

describe('real shared frontend HTTP/decoder contract (controlled transport)', () => {
  beforeEach(() => client.resetSession());

  it('encodes job identity and posts only current revision plus consent through CSRF, never keys', async () => {
    const id = 'controlled/id';
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(String(url).endsWith('/session') ? session : { ...authorizedJob, id }),
    );
    vi.stubGlobal('fetch', transport);
    await api.reauthorizeJobLLM(id, recoverySettings.revision);
    expect(transport).toHaveBeenCalledTimes(2);
    const [url, init] = transport.mock.calls[1]!;
    expect(url).toBe('/api/v1/jobs/controlled%2Fid/llm-authorization');
    expect(init).toMatchObject({
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRF-Token': session.csrf_token },
    });
    expect(JSON.parse(String(init?.body))).toEqual({ expected_revision: 17, consent: true });
  });

  it.each([
    { ...authorizedJob, id: 'foreign-job' },
    { ...authorizedJob, llm_recovery: { ...authorizedJob.llm_recovery!, remaining_calls: 9 } },
    {
      ...authorizedJob,
      stages: [{ ...authorizedJob.stages[0]!, repair: { regions: 1, unresolved: 2 } }],
    },
  ])(
    'marks invalid/wrong-job mutation responses uncertain and does not replay %#',
    async (response) => {
      const transport = vi.fn<typeof fetch>(async (url) =>
        json(String(url).endsWith('/session') ? session : response),
      );
      vi.stubGlobal('fetch', transport);
      await expect(api.reauthorizeJobLLM(recoveryJob.id, 17)).rejects.toMatchObject({
        code: 'invalid_write_response',
        uncertain: true,
      });
      expect(transport.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    },
  );

  it('keeps a lost POST result uncertain and never retries the request', async () => {
    const transport = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json(session))
      .mockRejectedValueOnce(new TypeError('controlled connection loss'));
    vi.stubGlobal('fetch', transport);
    await expect(api.reauthorizeJobLLM(recoveryJob.id, 17)).rejects.toMatchObject({
      uncertain: true,
      code: 'network_error',
    });
    expect(transport.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
  });

  it.each([-1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])(
    'rejects invalid expected revision %s before transport',
    (revision) => {
      const transport = vi.fn();
      vi.stubGlobal('fetch', transport);
      expect(() => api.reauthorizeJobLLM(recoveryJob.id, revision)).toThrow();
      expect(transport).not.toHaveBeenCalled();
    },
  );
});
