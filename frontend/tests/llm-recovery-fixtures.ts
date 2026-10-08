import type { LLMSettings } from '../src/api/llmTypes';
import type { Job } from '../src/api/types';
import { job } from './fixtures';

// Controlled credential-free DTOs, never imported by production source.
export const recoverySettings: LLMSettings = {
  revision: 17,
  endpoint: 'https://recovery-fixture.invalid/v1',
  model: 'synthetic-model',
  protocol: 'openai-compatible',
  response_mode: 'json-schema',
  mode: 'on-error',
  data_consent: true,
  key_configured: true,
  editable: true,
  status: 'ready',
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
export const recoveryJob: Job = {
  ...job,
  status: 'interrupted',
  can_resume: true,
  llm_recovery: {
    status: 'blocked',
    reason: 'authentication_failed',
    remaining_calls: 3,
    retry_after_seconds: null,
    can_reauthorize: true,
  },
};
export const authorizedJob: Job = {
  ...recoveryJob,
  llm_recovery: {
    ...recoveryJob.llm_recovery!,
    status: 'ready',
    reason: null,
    can_reauthorize: false,
  },
};
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
