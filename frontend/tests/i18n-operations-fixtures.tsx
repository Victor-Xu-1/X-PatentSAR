// Shared operations fixtures and suite-local lifecycle; tests/setup.ts remains the global setup.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, vi } from 'vitest';
import type { LLMApi } from '../src/api/llmApi';
import type { Job, Stage } from '../src/api/types';
import { setLocale } from '../src/i18n';
import { LLMApiPanel } from '../src/features/llm/LLMApiPanel';
import { pendingEnvironmentKey } from '../src/model/environmentRecovery';
import { job } from './fixtures';
import { recoverySettings } from './llm-recovery-fixtures';

export const switchTo = (locale: 'en' | 'zh-CN') => act(() => setLocale(locale));

export const syntheticKey = 'synthetic-unit-key-not-a-provider-credential';

export const controlledLLM = (): LLMApi => ({
  settings: vi.fn().mockResolvedValue(recoverySettings),
  save: vi.fn().mockResolvedValue(recoverySettings),
  test: vi.fn(),
});

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}

export async function openLLM(client = controlledLLM()) {
  render(<LLMApiPanel api={client} />);
  const opener = await screen.findByRole('button', { name: 'Configure' });
  await waitFor(() => expect(opener).toBeEnabled());
  await userEvent.click(opener);
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  expect(screen.getByRole('option', { name: 'Disabled (Off)' })).toHaveValue('off');
  return client;
}

export const change = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

export const progress: NonNullable<Stage['progress']> = {
  completed: 10,
  total: 10,
  cache_hits: 4,
  failures: 2,
  device: 'cpu',
  peak_rss_mb: 512,
};

export function rejectedJob(): Job {
  return {
    ...job,
    status: 'failed',
    error: { code: 'core_not_accepted', message: '设置已保存。' },
    task_note: '保存',
    stages: job.stages.map((stage) => ({
      ...stage,
      status: ['smiles', 'final', 'qa'].includes(stage.name) ? 'failed' : 'ok',
      ...(stage.name === 'smiles' ? { count: 10, progress } : {}),
    })),
  };
}

export function setupOperationsLocale() {
  beforeEach(() => {
    switchTo('en');
    sessionStorage.removeItem(pendingEnvironmentKey);
  });
  afterEach(() => {
    switchTo('en');
    sessionStorage.removeItem(pendingEnvironmentKey);
  });
}
