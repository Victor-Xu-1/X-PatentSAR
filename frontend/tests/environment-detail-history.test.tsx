import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { llmApi } from '../src/api/llmApi';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { setLocale } from '../src/i18n';
import { completeEnvironmentCatalog } from './environment-setup-fixtures';
import { health } from './fixtures';
import { historyList } from './history-fixtures';
import { recoverySettings } from './llm-recovery-fixtures';

beforeEach(() => {
  setLocale('en');
  vi.spyOn(api, 'environments').mockResolvedValue(completeEnvironmentCatalog());
  vi.spyOn(api, 'history').mockResolvedValue(historyList([]));
  vi.spyOn(llmApi, 'settings').mockResolvedValue({
    ...recoverySettings,
    mode: 'off',
    status: 'disabled',
    data_consent: false,
    key_configured: false,
  });
});

it('keeps operation records secondary and preserves unsaved locations, language and exact focus through nested history', async () => {
  const save = vi.spyOn(api, 'updateEnvironmentSettings');
  const start = vi.spyOn(api, 'createEnvironmentOperation');
  render(<EnvironmentPage product={health.product} operationId={null} onOperation={vi.fn()} />);
  const details = await screen.findByRole('button', { name: 'Environment details' });
  expect(screen.queryByRole('button', { name: 'Operation records' })).not.toBeInTheDocument();
  await userEvent.click(details);
  const parent = screen.getByRole('dialog', { name: 'Environment details' });
  const upload = within(parent).getByLabelText('Upload directory');
  fireEvent.change(upload, { target: { value: '/srv/wsl/data/new-private-upload' } });
  const opener = within(parent).getByRole('button', { name: 'Operation records' });
  await userEvent.click(opener);
  const records = await screen.findByRole('dialog', { name: 'Environment operation records' });
  expect(upload).toHaveValue('/srv/wsl/data/new-private-upload');
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('dialog', { name: '环境详情' })).toBe(parent);
  expect(screen.getByRole('dialog', { name: '环境操作记录' })).toBe(records);
  expect(within(parent).getByLabelText('上传文件目录')).toBe(upload);
  await userEvent.click(within(records).getByRole('button', { name: '关闭对话框' }));
  expect(opener).toHaveFocus();
  expect(upload).toHaveValue('/srv/wsl/data/new-private-upload');
  expect(save).not.toHaveBeenCalled();
  expect(start).not.toHaveBeenCalled();
  await userEvent.click(within(parent).getByRole('button', { name: '取消' }));
  expect(details).toHaveFocus();
});

it('retains independent record access when the component catalog is unavailable', async () => {
  vi.spyOn(api, 'environments').mockRejectedValue(
    new ApiError(503, 'controlled_catalog', 'Unavailable catalog'),
  );
  const start = vi.spyOn(api, 'createEnvironmentOperation');
  render(<EnvironmentPage product={health.product} operationId={null} onOperation={vi.fn()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Unavailable catalog');
  await userEvent.click(screen.getByRole('button', { name: 'Operation records' }));
  expect(
    await screen.findByRole('dialog', { name: 'Environment operation records' }),
  ).toBeVisible();
  expect(start).not.toHaveBeenCalled();
});
