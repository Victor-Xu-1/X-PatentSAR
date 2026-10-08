import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { llmApi } from '../src/api/llmApi';
import type { LLMSettings } from '../src/api/llmTypes';
import { LLMRecovery } from '../src/features/jobs/LLMRecovery';
import { LLMApiPanel } from '../src/features/llm/LLMApiPanel';
import { recoveryJob, recoverySettings } from './llm-recovery-fixtures';
import {
  change,
  controlledLLM,
  deferred,
  openLLM,
  setupOperationsLocale,
  switchTo,
  syntheticKey,
} from './i18n-operations-fixtures';

setupOperationsLocale();

describe('operations locale: llm', () => {
  it('switches an open LLM draft and accessible names without remounting or requests', async () => {
    const client = await openLLM();
    change('Model', '设置已保存。');
    change('API key', syntheticKey);
    const model = screen.getByLabelText('Model');
    const dialog = screen.getByRole('dialog', { name: 'LLM API settings' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: 'LLM API 设置' })).toBe(dialog);
    expect(screen.getByLabelText('模型')).toBe(model);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'LLM API settings' })).toBe(dialog);
    expect(screen.getByLabelText('Model')).toBe(model);
    expect(model).toHaveValue('设置已保存。');
    expect(screen.getByLabelText('API key')).toHaveValue(syntheticKey);
    expect(screen.getByLabelText('API protocol')).toHaveValue('openai-compatible');
    expect(screen.getByLabelText('JSON format')).toHaveValue('json-schema');
    expect(screen.getByLabelText('Review mode')).toHaveValue('on-error');
    expect(screen.getByRole('checkbox', { name: /I consent to sending/ })).toBeChecked();
    expect(screen.getByText(/Up to 8 calls per task/)).toHaveTextContent('12000/16000 characters');
    switchTo('zh-CN');
    expect(screen.getByLabelText('模型')).toBe(model);
    expect(model).toHaveValue('设置已保存。');
    expect(client.settings).toHaveBeenCalledTimes(1);
    expect(client.save).not.toHaveBeenCalled();
    expect(client.test).not.toHaveBeenCalled();
  });

  it('relocalizes a stored LLM write error without resubmitting or exposing provider text', async () => {
    const client = controlledLLM();
    vi.mocked(client.save).mockRejectedValue(
      new ApiError(422, 'invalid', 'synthetic-private-provider-body'),
    );
    await openLLM(client);
    change('Model', 'changed-model');
    change('API key', syntheticKey);
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Settings were not accepted.');
    switchTo('zh-CN');
    expect(await screen.findByRole('alert')).toHaveTextContent('配置未被接受');
    switchTo('en');
    expect(screen.getByRole('alert')).toHaveTextContent('Settings were not accepted.');
    expect(screen.queryByText(/synthetic-private-provider-body/)).not.toBeInTheDocument();
    switchTo('zh-CN');
    expect(screen.getByRole('alert')).toHaveTextContent('配置未被接受');
    expect(client.save).toHaveBeenCalledTimes(1);
    expect(client.test).not.toHaveBeenCalled();
  });

  it('preserves the explicit API test confirmation without sending a test on language changes', async () => {
    const client = await openLLM();
    await userEvent.click(screen.getByRole('button', { name: 'Test API' }));
    const confirmation = screen.getByRole('dialog', { name: 'Confirm API test' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '确认接口测试' })).toBe(confirmation);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Confirm API test' })).toBe(confirmation);
    expect(within(confirmation).getByText(/API charges may apply/)).toBeVisible();
    expect(
      within(confirmation).getByRole('button', { name: 'Confirm test request' }),
    ).toBeEnabled();
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '确认接口测试' })).toBe(confirmation);
    expect(client.test).not.toHaveBeenCalled();
  });

  it('updates recovery reasons, quotas and an open authorization confirmation without renewing', async () => {
    vi.spyOn(llmApi, 'settings').mockResolvedValue(recoverySettings);
    const renew = vi.spyOn(api, 'reauthorizeJobLLM');
    const controls = {
      eligible: true,
      disabled: false,
      acquire: vi.fn(() => true),
      release: vi.fn(),
      awaitRefresh: vi.fn(),
      onChange: vi.fn(),
    };
    render(<LLMRecovery job={recoveryJob} controls={controls} />);
    await userEvent.click(screen.getByRole('button', { name: 'Renew API authorization' }));
    await screen.findByText(recoverySettings.endpoint);
    const dialog = screen.getByRole('dialog', { name: 'Renew this task’s API authorization?' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '更新此任务的 API 授权？' })).toBe(dialog);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Renew this task’s API authorization?' })).toBe(
      dialog,
    );
    expect(screen.getByRole('region', { name: 'LLM local repair' })).toHaveTextContent(
      'Remaining calls: 3',
    );
    expect(screen.getByText(/API authentication failed/)).toBeVisible();
    expect(within(dialog).getByText('openai-compatible')).toBeVisible();
    expect(within(dialog).getByText(/Quota is not reset/)).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '更新此任务的 API 授权？' })).toBe(dialog);
    expect(llmApi.settings).toHaveBeenCalledTimes(1);
    expect(renew).not.toHaveBeenCalled();
  });

  it.each([
    ['disabled', '已关闭', 'Disabled'],
    ['incomplete', '配置未完成', 'Configuration incomplete'],
    ['ready', '已配置', 'Configured'],
  ] as const)(
    'relocalizes a delayed %s LLM status without rereading settings',
    async (status, zh, en) => {
      const pending = deferred<LLMSettings>();
      const client = controlledLLM();
      vi.mocked(client.settings).mockReturnValue(pending.promise);
      render(<LLMApiPanel api={client} />);
      expect(screen.getByLabelText('LLM API status')).toHaveTextContent('Loading…');
      expect(screen.getByRole('button', { name: 'Configure' })).toBeDisabled();
      switchTo('zh-CN');
      expect(screen.getByLabelText('LLM API 状态')).toHaveTextContent('正在读取…');
      await act(async () => pending.resolve({ ...recoverySettings, status }));
      expect(screen.getByLabelText('LLM API 状态')).toHaveTextContent(zh);
      switchTo('en');
      expect(screen.getByLabelText('LLM API status')).toHaveTextContent(en);
      expect(client.settings).toHaveBeenCalledTimes(1);
      expect(client.save).not.toHaveBeenCalled();
      expect(client.test).not.toHaveBeenCalled();
    },
  );

  it('keeps an in-flight LLM draft and re-localizes its saved result without another write', async () => {
    const pending = deferred<LLMSettings>();
    const client = controlledLLM();
    vi.mocked(client.save).mockReturnValue(pending.promise);
    await openLLM(client);
    change('Model', '保存');
    change('API key', syntheticKey);
    const input = screen.getByLabelText('Model');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByRole('button', { name: 'Processing…' })).toBeDisabled();
    switchTo('zh-CN');
    expect(screen.getByLabelText('模型')).toBe(input);
    expect(input).toHaveValue('保存');
    expect(screen.getByLabelText('API 密钥')).toHaveValue(syntheticKey);
    expect(screen.getByRole('button', { name: '处理中…' })).toBeDisabled();
    await act(async () => pending.resolve({ ...recoverySettings, revision: 18, model: '保存' }));
    expect(screen.getByText('设置已保存。')).toBeVisible();
    switchTo('en');
    expect(screen.getByText('Settings saved.')).toBeVisible();
    expect(screen.getByLabelText('Model')).toBe(input);
    expect(input).toHaveValue('保存');
    expect(screen.getByLabelText('API key')).toHaveValue('');
    expect(client.save).toHaveBeenCalledTimes(1);
    expect(client.settings).toHaveBeenCalledTimes(1);
    expect(client.test).not.toHaveBeenCalled();
  });

  it('relocalizes a retained delayed read error and never echoes a provider body', async () => {
    const pending = deferred<LLMSettings>();
    const client = controlledLLM();
    vi.mocked(client.settings).mockReturnValue(pending.promise);
    render(<LLMApiPanel api={client} />);
    switchTo('zh-CN');
    await act(async () =>
      pending.reject(new ApiError(503, 'unavailable', 'synthetic-private-body')),
    );
    expect(screen.getByRole('alert')).toHaveTextContent('无法读取 LLM API 设置。');
    switchTo('en');
    expect(screen.getByRole('alert')).toHaveTextContent('Could not read LLM API settings.');
    expect(screen.queryByText(/synthetic-private-body/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Configure' })).toBeDisabled();
    expect(client.settings).toHaveBeenCalledTimes(1);
  });
});
