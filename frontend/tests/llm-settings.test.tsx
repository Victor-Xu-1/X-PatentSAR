import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiClient } from '../src/api/client';
import { ApiError } from '../src/api/errors';
import { createLLMApi, llmApi } from '../src/api/llmApi';
import type { LLMApi } from '../src/api/llmApi';
import { decodeLLMSettings, decodeLLMTestResult } from '../src/api/llmDecoders';
import type { LLMSettings, LLMTestResult } from '../src/api/llmTypes';
import { ContractError } from '../src/api/validation';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { LLMApiPanel } from '../src/features/llm/LLMApiPanel';
import { llmDraft, llmSaveRequest, updateLLMDraft } from '../src/features/llm/llmDraft';
import { health, json, session } from './fixtures';

const syntheticKey = 'synthetic-unit-key-not-a-provider-credential';
const initial: LLMSettings = {
  revision: 0,
  endpoint: '',
  model: '',
  protocol: 'openai-compatible',
  response_mode: 'json-schema',
  mode: 'off',
  data_consent: false,
  key_configured: false,
  editable: true,
  status: 'disabled',
  reason: null,
  limits: {
    max_calls: 8,
    timeout_seconds: 30,
    max_input_chars: 12000,
    max_output_chars: 16000,
    max_tokens: 1024,
  },
  last_test: null,
};
const ready: LLMSettings = {
  ...initial,
  revision: 4,
  endpoint: 'https://llm-fixture.invalid/v1',
  model: 'synthetic-model',
  mode: 'on-error',
  data_consent: true,
  key_configured: true,
  status: 'ready',
};
const passed: LLMTestResult = {
  status: 'passed',
  reason: 'synthetic_ok',
  settings_revision: ready.revision,
  checked_at: '2026-10-08T00:00:00Z',
};
function controlled(settings: LLMSettings = initial): LLMApi {
  return {
    settings: vi.fn().mockResolvedValue(settings),
    save: vi.fn().mockResolvedValue(settings),
    test: vi.fn().mockResolvedValue(passed),
  };
}
async function open(settings: LLMSettings = initial) {
  const api = controlled(settings);
  const view = render(<LLMApiPanel api={api} />);
  const opener = await screen.findByRole('button', { name: '配置' });
  await waitFor(() => expect(opener).toBeEnabled());
  await userEvent.click(opener);
  return { api, view, opener, dialog: screen.getByRole('dialog', { name: 'LLM API 设置' }) };
}
function change(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
async function enableDraft() {
  change('HTTPS API 基础地址', ready.endpoint);
  change('模型', ready.model);
  change('API 密钥', syntheticKey);
  await userEvent.selectOptions(screen.getByLabelText('复核模式'), 'on-error');
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('minimal independent LLM API settings', () => {
  it.each([
    { label: 'not tested', result: null, passVisible: false, failureVisible: false },
    { label: 'current passed test', result: passed, passVisible: true, failureVisible: false },
    {
      label: 'current failed test',
      result: { ...passed, status: 'failed' as const },
      passVisible: false,
      failureVisible: true,
    },
    {
      label: 'stale passed test',
      result: { ...passed, settings_revision: 3 },
      passVisible: false,
      failureVisible: false,
    },
  ])(
    'uses configuration-only status without inventing provider availability: $label',
    async ({ result, passVisible, failureVisible }) => {
      const { api } = await open({ ...ready, last_test: result });
      expect(screen.getByLabelText('LLM API 状态')).toHaveTextContent('已配置');
      expect(screen.getByLabelText('LLM API 状态')).not.toHaveTextContent(/已就绪|已可用|已验证/);
      expect(screen.queryByText('接口测试通过。') !== null).toBe(passVisible);
      expect(screen.queryByText(/接口测试失败/) !== null).toBe(failureVisible);
      expect(api.test).not.toHaveBeenCalled();
    },
  );

  it('shows the concise future-task and inherited resume quota boundary exactly once', async () => {
    const { api } = await open();
    const note = '设置变更仅影响后续新任务；续跑沿用原配置快照与剩余调用配额。';
    expect(screen.getAllByText(note)).toHaveLength(1);
    expect(screen.getByText(note)).toBeVisible();
    expect(api.save).not.toHaveBeenCalled();
    expect(api.test).not.toHaveBeenCalled();
  });

  it('does not fabricate Off/ready while loading and never saves/tests on render', async () => {
    const pending = deferred<LLMSettings>();
    const api = controlled();
    vi.mocked(api.settings).mockReturnValue(pending.promise);
    render(<LLMApiPanel api={api} />);
    expect(screen.getByLabelText('LLM API 状态')).toHaveTextContent('正在读取');
    expect(screen.getByRole('button', { name: '配置' })).toBeDisabled();
    await act(async () => pending.resolve(initial));
    expect(screen.getByLabelText('LLM API 状态')).toHaveTextContent('已关闭');
    expect(screen.getAllByText('仅外部 API，不在本机部署模型')).toHaveLength(1);
    expect(api.save).not.toHaveBeenCalled();
    expect(api.test).not.toHaveBeenCalled();
    expect(screen.queryByText(/日志|历史|revision|request_id/)).not.toBeInTheDocument();
  });

  it('renders the panel even when the environment catalog fails', async () => {
    vi.spyOn(api, 'environments').mockRejectedValue(new ApiError(404, 'missing', '环境不可用'));
    vi.spyOn(llmApi, 'settings').mockResolvedValue(initial);
    render(<EnvironmentPage product={health.product} operationId={null} onOperation={vi.fn()} />);
    expect(await screen.findByText(/当前后端未提供环境管理/)).toBeVisible();
    const panel = screen.getByRole('region', { name: 'LLM API' });
    expect(within(panel).getByLabelText('LLM API 状态')).toHaveTextContent('已关闭');
    await userEvent.click(within(panel).getByRole('button', { name: '配置' }));
    expect(screen.getByRole('dialog', { name: 'LLM API 设置' })).toBeVisible();
  });

  it('offers explicit retry for an unavailable API without showing raw error/credentials', async () => {
    const api = controlled();
    vi.mocked(api.settings).mockRejectedValueOnce(new ApiError(404, 'missing', syntheticKey));
    render(<LLMApiPanel api={api} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('当前后端尚未提供 LLM API 设置');
    expect(screen.getByRole('button', { name: '配置' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    await waitFor(() => expect(screen.getByLabelText('LLM API 状态')).toHaveTextContent('已关闭'));
    expect(api.settings).toHaveBeenCalledTimes(2);
    expect(document.body.textContent).not.toContain(syntheticKey);
  });

  it('opens defaults, focuses the endpoint, and destroys an unsaved key on close', async () => {
    const { opener } = await open();
    expect(screen.getByLabelText('HTTPS API 基础地址')).toHaveFocus();
    expect(screen.getByLabelText('复核模式')).toHaveValue('off');
    expect(screen.queryByRole('button', { name: '测试接口' })).not.toBeInTheDocument();
    const key = screen.getByLabelText('API 密钥');
    expect(key).toHaveAttribute('type', 'password');
    expect(key).toHaveAttribute('autocomplete', 'new-password');
    change('API 密钥', syntheticKey);
    await userEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(opener).toHaveFocus();
    await userEvent.click(opener);
    expect(screen.getByLabelText('API 密钥')).toHaveValue('');
  });

  it('requires disclosure consent, saves with CAS, resets the key and does not automatically test', async () => {
    const { api } = await open();
    vi.mocked(api.save).mockResolvedValue(ready);
    await enableDraft();
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
    await userEvent.click(screen.getByLabelText('我同意向所选外部 API 发送有限的局部文字'));
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(api.save).toHaveBeenCalledExactlyOnceWith({
      expected_revision: 0,
      endpoint: ready.endpoint,
      model: ready.model,
      protocol: 'openai-compatible',
      response_mode: 'json-schema',
      mode: 'on-error',
      data_consent: true,
      api_key: syntheticKey,
    });
    expect(await screen.findByText('设置已保存。')).toBeVisible();
    expect(screen.getByLabelText('API 密钥')).toHaveValue('');
    expect(screen.getByLabelText('LLM API 状态')).toHaveTextContent('已配置');
    expect(screen.getByRole('button', { name: '测试接口' })).toBeEnabled();
    expect(api.test).not.toHaveBeenCalled();
  });

  it('omits a blank key to retain it when changing only the enabled mode', async () => {
    const { api } = await open(ready);
    await userEvent.selectOptions(screen.getByLabelText('复核模式'), 'quality');
    expect(screen.getByRole('button', { name: '测试接口' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(api.save).toHaveBeenCalledExactlyOnceWith({
      expected_revision: 4,
      endpoint: ready.endpoint,
      model: ready.model,
      protocol: 'openai-compatible',
      response_mode: 'json-schema',
      mode: 'quality',
      data_consent: true,
    });
  });

  it('keeps protocol choice user-configured with no endpoint or model presets', async () => {
    const { api } = await open();
    expect(screen.getByLabelText('API 协议')).toHaveValue('openai-compatible');
    expect(screen.getByLabelText('JSON 格式')).toHaveValue('json-schema');
    expect(screen.getByText('响应格式', { selector: 'summary' }).parentElement).not.toHaveAttribute(
      'open',
    );
    for (const protocol of ['anthropic', 'gemini', 'openai-compatible']) {
      await userEvent.selectOptions(screen.getByLabelText('API 协议'), protocol);
      expect(screen.getByLabelText('HTTPS API 基础地址')).toHaveValue('');
      expect(screen.getByLabelText('模型')).toHaveValue('');
      if (protocol !== 'openai-compatible')
        expect(screen.queryByLabelText('JSON 格式')).not.toBeInTheDocument();
    }
    expect(api.save).not.toHaveBeenCalled();
  });

  it.each(['json-schema', 'json-object', 'prompt-only'])(
    'saves explicit compatible response mode %s without replacing the unchanged key',
    async (responseMode) => {
      const { api } = await open({
        ...ready,
        response_mode: responseMode === 'json-schema' ? 'json-object' : 'json-schema',
      });
      await userEvent.click(screen.getByText('响应格式', { selector: 'summary' }));
      await userEvent.selectOptions(screen.getByLabelText('JSON 格式'), responseMode);
      await userEvent.click(screen.getByRole('button', { name: '保存' }));
      expect(api.save).toHaveBeenCalledExactlyOnceWith(
        expect.objectContaining({ protocol: 'openai-compatible', response_mode: responseMode }),
      );
      expect(vi.mocked(api.save).mock.calls[0]![0]).not.toHaveProperty('api_key');
    },
  );

  it.each(['anthropic', 'gemini'])(
    'saves %s with a new key and the fixed native response default',
    async (protocol) => {
      const { api } = await open({ ...ready, response_mode: 'prompt-only' });
      change('API 密钥', syntheticKey);
      await userEvent.selectOptions(screen.getByLabelText('API 协议'), protocol);
      expect(screen.getByLabelText('API 密钥')).toHaveValue('');
      expect(screen.queryByLabelText('JSON 格式')).not.toBeInTheDocument();
      change('API 密钥', syntheticKey);
      await userEvent.click(screen.getByRole('button', { name: '保存' }));
      expect(api.save).toHaveBeenCalledExactlyOnceWith(
        expect.objectContaining({ protocol, response_mode: 'json-schema', api_key: syntheticKey }),
      );
    },
  );

  it.each(['HTTPS API 基础地址', '模型'])(
    'drops a key entered for an earlier draft when %s changes',
    async (label) => {
      await open(ready);
      change('API 密钥', syntheticKey);
      change(label, label === '模型' ? 'different-model' : 'https://different-fixture.invalid/v1');
      expect(screen.getByLabelText('API 密钥')).toHaveValue('');
    },
  );

  it.each(['HTTPS API 基础地址', '模型', 'API 协议'])(
    'requires replacement or explicit clearing after %s changes',
    async (label) => {
      const { api } = await open(ready);
      change(
        label,
        label === 'API 协议'
          ? 'anthropic'
          : label === '模型'
            ? 'another-synthetic-model'
            : 'https://another-fixture.invalid/v1',
      );
      await userEvent.click(screen.getByRole('button', { name: '保存' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('地址、模型或协议已改变');
      expect(api.save).not.toHaveBeenCalled();
      await userEvent.click(screen.getByLabelText('清除密钥并关闭'));
      expect(screen.getByLabelText('复核模式')).toHaveValue('off');
      expect(screen.getByLabelText('我同意向所选外部 API 发送有限的局部文字')).not.toBeChecked();
      await userEvent.click(screen.getByRole('button', { name: '保存' }));
      expect(api.save).toHaveBeenCalledExactlyOnceWith(
        expect.objectContaining({ api_key: '', mode: 'off', data_consent: false }),
      );
    },
  );

  it('can save disabled synthetic configuration by explicitly clearing its empty key', async () => {
    const { api } = await open();
    change('HTTPS API 基础地址', ready.endpoint);
    change('模型', ready.model);
    await userEvent.click(screen.getByLabelText('清除密钥并关闭'));
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(api.save).toHaveBeenCalledExactlyOnceWith({
      expected_revision: 0,
      endpoint: ready.endpoint,
      model: ready.model,
      protocol: 'openai-compatible',
      response_mode: 'json-schema',
      mode: 'off',
      data_consent: false,
      api_key: '',
    });
  });

  it('disabling preserves a configured key without authorizing any API call; clearing is explicit', async () => {
    const { api } = await open(ready);
    change('API 密钥', syntheticKey);
    await userEvent.selectOptions(screen.getByLabelText('复核模式'), 'off');
    expect(screen.getByLabelText('API 密钥')).toHaveValue(syntheticKey);
    expect(screen.getByLabelText('清除密钥并关闭')).not.toBeChecked();
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(api.save).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ mode: 'off', api_key: syntheticKey, data_consent: false }),
    );
  });

  it.each([
    'http://llm-fixture.invalid/v1',
    'https://user:key@llm-fixture.invalid/v1',
    'https://llm-fixture.invalid/v1?api_key=synthetic',
    'https://llm-fixture.invalid/v1#key',
    'https://llm-fixture.invalid\\bad',
  ])('rejects an unsafe endpoint without making a request: %s', async (endpoint) => {
    const { api } = await open();
    change('HTTPS API 基础地址', endpoint);
    await userEvent.click(screen.getByLabelText('清除密钥并关闭'));
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTPS API 基础地址');
    expect(api.save).not.toHaveBeenCalled();
  });

  it('keeps nonsecret drafts on rejected saves and never renders echoed keys or writes browser storage', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    const { api } = await open(ready);
    vi.mocked(api.save).mockRejectedValue(new ApiError(422, 'bad_key', syntheticKey));
    change('API 密钥', syntheticKey);
    await userEvent.selectOptions(screen.getByLabelText('复核模式'), 'quality');
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('配置未被接受');
    expect(screen.getByLabelText('复核模式')).toHaveValue('quality');
    expect(screen.getByLabelText('API 密钥')).toHaveValue('');
    expect(document.body.textContent).not.toContain(syntheticKey);
    expect(document.body.innerHTML).not.toContain(syntheticKey);
    expect(storage).not.toHaveBeenCalled();
  });

  it('requires refresh plus explicit CAS reconciliation and preserves the nonsecret form', async () => {
    const { api } = await open(ready);
    vi.mocked(api.save).mockRejectedValueOnce(new ApiError(409, 'conflict', syntheticKey));
    vi.mocked(api.settings).mockResolvedValue({ ...ready, revision: 5 });
    await userEvent.selectOptions(screen.getByLabelText('复核模式'), 'quality');
    change('API 密钥', syntheticKey);
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('请先刷新');
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '刷新服务器状态' }));
    await userEvent.click(await screen.findByRole('button', { name: '使用最新版本并保留输入' }));
    expect(screen.getByLabelText('复核模式')).toHaveValue('quality');
    expect(screen.getByLabelText('API 密钥')).toHaveValue('');
    expect(api.save).toHaveBeenCalledTimes(1);
    vi.mocked(api.save).mockResolvedValue({ ...ready, revision: 6, mode: 'quality' });
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(api.save).toHaveBeenLastCalledWith(
      expect.objectContaining({ expected_revision: 5, mode: 'quality' }),
    );
  });

  it('blocks an uncertain write until a successful GET; a failed refresh cannot unlock retry', async () => {
    const { api } = await open(ready);
    vi.mocked(api.save).mockRejectedValue(
      new ApiError(200, 'invalid_write_response', syntheticKey, true),
    );
    await userEvent.selectOptions(screen.getByLabelText('复核模式'), 'quality');
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('结果尚未确认');
    vi.mocked(api.settings).mockRejectedValueOnce(new Error(syntheticKey));
    await userEvent.click(screen.getByRole('button', { name: '刷新服务器状态' }));
    expect(await screen.findByText('无法读取 LLM API 设置。')).toBeVisible();
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
    expect(screen.getByLabelText('LLM API 状态')).toHaveTextContent('无法读取');
    vi.mocked(api.settings).mockResolvedValue(ready);
    await userEvent.click(screen.getByRole('button', { name: '刷新服务器状态' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).toBeEnabled());
    expect(screen.getByLabelText('复核模式')).toHaveValue('quality');
    expect(api.save).toHaveBeenCalledTimes(1);
  });

  it('locks dismissal and duplicate saves while a write is in flight', async () => {
    const { api, dialog } = await open(ready);
    const pending = deferred<LLMSettings>();
    vi.mocked(api.save).mockReturnValue(pending.promise);
    change('API 密钥', syntheticKey);
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(screen.getByRole('button', { name: '关闭对话框' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '取消' })).toBeDisabled();
    fireEvent(dialog, new Event('cancel', { cancelable: true }));
    fireEvent.submit(dialog.querySelector('form')!);
    expect(dialog).toBeVisible();
    expect(api.save).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve({ ...ready, revision: 5 }));
    expect(screen.getByLabelText('API 密钥')).toHaveValue('');
  });

  it('retains a read-recovery action after closing an uncertain save instead of trapping Configure disabled', async () => {
    const { api } = await open(ready);
    vi.mocked(api.save).mockRejectedValue(new ApiError(0, 'network_error', syntheticKey, true));
    await userEvent.selectOptions(screen.getByLabelText('复核模式'), 'quality');
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    await screen.findByRole('button', { name: '刷新服务器状态' });
    await userEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.getByRole('button', { name: '配置' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('请先读取服务器状态');
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '配置' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: '配置' }));
    expect(screen.getByLabelText('API 密钥')).toHaveValue('');
    expect(api.save).toHaveBeenCalledTimes(1);
  });

  it('requires an explicit synthetic-test confirmation; cancelling restores focus without a call', async () => {
    const { api } = await open(ready);
    const testButton = screen.getByRole('button', { name: '测试接口' });
    await userEvent.click(testButton);
    const confirmation = screen.getByRole('dialog', { name: '确认接口测试' });
    expect(confirmation).toHaveTextContent('固定的合成文本');
    expect(confirmation).toHaveTextContent('可能产生 API 费用');
    expect(within(confirmation).getByRole('button', { name: '取消测试' })).toHaveFocus();
    expect(api.test).not.toHaveBeenCalled();
    await userEvent.click(within(confirmation).getByRole('button', { name: '取消测试' }));
    expect(testButton).toHaveFocus();
    expect(api.test).not.toHaveBeenCalled();
    await userEvent.click(testButton);
    await userEvent.click(screen.getByRole('button', { name: '确认发送测试' }));
    expect(api.test).toHaveBeenCalledExactlyOnceWith(4, 30);
    expect(await screen.findByText('接口测试通过。')).toBeVisible();
  });

  it('keeps test cancellation/close busy-safe and uses actual failed API status without echoed secrets', async () => {
    const { api } = await open(ready);
    const pending = deferred<LLMTestResult>();
    vi.mocked(api.test).mockReturnValue(pending.promise);
    await userEvent.click(screen.getByRole('button', { name: '测试接口' }));
    const confirmation = screen.getByRole('dialog', { name: '确认接口测试' });
    await userEvent.click(within(confirmation).getByRole('button', { name: '确认发送测试' }));
    expect(within(confirmation).getByRole('button', { name: '取消测试' })).toBeDisabled();
    expect(within(confirmation).getByRole('button', { name: '关闭对话框' })).toBeDisabled();
    fireEvent(confirmation, new Event('cancel', { cancelable: true }));
    expect(confirmation).toBeVisible();
    expect(api.test).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve({ ...passed, status: 'failed', reason: syntheticKey }));
    expect(await screen.findByText(/接口测试失败/)).toBeVisible();
    expect(screen.queryByRole('dialog', { name: '确认接口测试' })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(syntheticKey);
  });

  it('never replays an uncertain test and requires a read before another confirmation', async () => {
    const { api } = await open(ready);
    vi.mocked(api.test).mockRejectedValue(new ApiError(0, 'timeout', syntheticKey, true));
    await userEvent.click(screen.getByRole('button', { name: '测试接口' }));
    await userEvent.click(screen.getByRole('button', { name: '确认发送测试' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('结果尚未确认');
    expect(screen.getByRole('button', { name: '测试接口' })).toBeDisabled();
    expect(api.test).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: '刷新服务器状态' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '测试接口' })).toBeEnabled());
    expect(api.test).toHaveBeenCalledTimes(1);
  });

  it('does not present a previous-revision test as current and hides tests for incomplete settings', async () => {
    const view = await open({ ...ready, last_test: { ...passed, settings_revision: 3 } });
    expect(screen.queryByText('接口测试通过。')).not.toBeInTheDocument();
    view.view.unmount();
    await open({ ...ready, key_configured: false, status: 'incomplete', reason: 'missing_key' });
    expect(screen.getByLabelText('LLM API 状态')).toHaveTextContent('配置未完成');
    expect(screen.queryByRole('button', { name: '测试接口' })).not.toBeInTheDocument();
  });

  it('is read-only under environment overrides and never acquires editing authority from a draft', async () => {
    const { api } = await open({ ...ready, editable: false });
    expect(screen.getByText('配置由环境变量管理，网页只读。')).toBeVisible();
    expect(screen.getByLabelText('HTTPS API 基础地址')).toBeDisabled();
    expect(screen.getByLabelText('API 密钥')).toBeDisabled();
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('API 密钥'), { target: { value: syntheticKey } });
    fireEvent.submit(screen.getByRole('dialog').querySelector('form')!);
    expect(api.save).not.toHaveBeenCalled();
  });
});

describe('strict credential-free REST boundary', () => {
  it.each([
    { ...initial, api_key: syntheticKey },
    { ...initial, token: syntheticKey },
    { ...initial, limits: { ...initial.limits, authorization: syntheticKey } },
    { ...ready, last_test: { ...passed, api_key: syntheticKey } },
    { ...initial, key_configured: 'false' },
    { ...initial, revision: 0.5 },
    { ...initial, protocol: 'unknown' },
    { ...initial, protocol: undefined },
    { ...initial, response_mode: 'text' },
    { ...initial, response_mode: undefined },
    { ...initial, reason: undefined },
    { ...initial, last_test: undefined },
    { ...initial, status: 'ready' },
    { ...ready, key_configured: false },
    { ...initial, limits: { ...initial.limits, timeout_seconds: -1 } },
    { ...ready, endpoint: 'https://user:key@llm-fixture.invalid/v1' },
    { ...ready, last_test: { ...passed, settings_revision: 5 } },
  ])(
    'rejects unexpected credentials, omitted fields, types and contradictory status %#',
    (input) => {
      expect(() => decodeLLMSettings(input)).toThrow(ContractError);
      try {
        decodeLLMSettings(input);
      } catch (error) {
        expect(String(error)).not.toContain(syntheticKey);
      }
    },
  );

  it('rejects extra credential fields and invalid timestamps in test results', () => {
    expect(() => decodeLLMTestResult({ ...passed, api_key: syntheticKey })).toThrow(ContractError);
    expect(() => decodeLLMTestResult({ ...passed, checked_at: 'yesterday' })).toThrow(
      ContractError,
    );
    expect(decodeLLMSettings(initial)).toEqual(initial);
    expect(decodeLLMSettings(ready)).toEqual(ready);
  });

  it('uses one client session, same-origin requests and CSRF; keys remain only in the PUT body', async () => {
    const transport = vi.fn<typeof fetch>(async (url, init) => {
      if (String(url).endsWith('/session')) return json(session);
      if (String(url).endsWith('/llm/test')) return json(passed);
      return json(init?.method === 'PUT' ? ready : initial);
    });
    const shared = new ApiClient(transport);
    const api = createLLMApi(shared);
    await shared.bootstrap();
    await api.settings(new AbortController().signal);
    await api.save({
      expected_revision: 0,
      endpoint: ready.endpoint,
      model: ready.model,
      protocol: 'openai-compatible',
      response_mode: 'json-schema',
      mode: 'on-error',
      data_consent: true,
      api_key: syntheticKey,
    });
    await api.test(4, 30);
    expect(transport.mock.calls.filter(([url]) => String(url).endsWith('/session'))).toHaveLength(
      1,
    );
    const put = transport.mock.calls.find(([, init]) => init?.method === 'PUT')!;
    expect(put[0]).toBe('/api/v1/llm/settings');
    expect(put[1]).toMatchObject({
      credentials: 'same-origin',
      headers: { 'X-CSRF-Token': session.csrf_token },
    });
    expect(JSON.parse(put[1]!.body as string)).toHaveProperty('api_key', syntheticKey);
    const post = transport.mock.calls.find(([, init]) => init?.method === 'POST')!;
    expect(JSON.parse(post[1]!.body as string)).toEqual({ expected_revision: 4, consent: true });
    for (const [url, options] of transport.mock.calls) {
      expect(String(url)).toMatch(/^\/api\/v1\//);
      expect(String(url)).not.toContain(syntheticKey);
      expect(JSON.stringify(options?.headers)).not.toContain(syntheticKey);
    }
  });

  it('classifies a credential-bearing PUT response as uncertain and never exposes its key', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(String(url).endsWith('/session') ? session : { ...ready, api_key: syntheticKey }),
    );
    const api = createLLMApi(new ApiClient(transport));
    const request = api.save({
      expected_revision: 4,
      endpoint: ready.endpoint,
      model: ready.model,
      protocol: 'openai-compatible',
      response_mode: 'json-schema',
      mode: 'quality',
      data_consent: true,
    });
    await expect(request).rejects.toMatchObject({
      code: 'invalid_write_response',
      uncertain: true,
    });
    await expect(request).rejects.not.toThrow(syntheticKey);
    expect(transport.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1);
  });

  it('rejects a test response from another settings revision instead of fabricating a result', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(String(url).endsWith('/session') ? session : { ...passed, settings_revision: 3 }),
    );
    await expect(createLLMApi(new ApiClient(transport)).test(4, 30)).rejects.toMatchObject({
      uncertain: true,
    });
  });

  it('defends direct draft callers against missing consent and retaining a key after identity changes', () => {
    expect(() => llmSaveRequest({ ...llmDraft(ready), model: 'changed' }, ready)).toThrow(
      '地址、模型或协议',
    );
    expect(() => llmSaveRequest({ ...llmDraft(ready), dataConsent: false }, ready)).toThrow(
      '明确同意',
    );
    expect(llmSaveRequest({ ...llmDraft(initial), apiKey: syntheticKey }, initial)).toMatchObject({
      mode: 'off',
      data_consent: false,
      api_key: syntheticKey,
    });
    expect(
      llmSaveRequest(updateLLMDraft(llmDraft(ready), { clearKey: true }), ready),
    ).toMatchObject({ mode: 'off', data_consent: false, api_key: '' });
  });

  it.each([0, 31, 127])(
    'rejects control character %i in models, keys and response text',
    (code) => {
      const value = `synthetic${String.fromCharCode(code)}value`;
      expect(() =>
        llmSaveRequest({ ...llmDraft(ready), model: value, apiKey: syntheticKey }, ready),
      ).toThrow('模型名称无效');
      expect(() => llmSaveRequest({ ...llmDraft(ready), apiKey: value }, ready)).toThrow(
        '密钥格式无效',
      );
      expect(() => decodeLLMSettings({ ...initial, reason: value })).toThrow(ContractError);
    },
  );
});
