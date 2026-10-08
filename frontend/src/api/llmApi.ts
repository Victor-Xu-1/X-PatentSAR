import type { ApiClient } from './client';
import { client } from './index';
import { decodeLLMSettings, decodeLLMTestResult } from './llmDecoders';
import type { LLMSettingsUpdate } from './llmTypes';
import { ContractError } from './validation';

export function createLLMApi(apiClient: ApiClient) {
  return {
    settings: (signal: AbortSignal) => apiClient.get('/llm/settings', decodeLLMSettings, signal),
    save: (request: LLMSettingsUpdate) =>
      apiClient.mutate('/llm/settings', 'PUT', request, decodeLLMSettings),
    test: (expectedRevision: number, timeoutSeconds: number) =>
      apiClient.mutate(
        '/llm/test',
        'POST',
        { expected_revision: expectedRevision, consent: true },
        (value) => {
          const result = decodeLLMTestResult(value);
          if (result.settings_revision !== expectedRevision)
            throw new ContractError('$.settings_revision');
          return result;
        },
        { timeoutMs: Math.min(timeoutSeconds * 1000 + 10_000, 130_000) },
      ),
  };
}

// Same session, CSRF and bounded transport as the rest of the workbench.
export const llmApi = createLLMApi(client);
export type LLMApi = ReturnType<typeof createLLMApi>;
