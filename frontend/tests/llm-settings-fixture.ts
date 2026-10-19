import type { LLMSettings } from '../src/api/llmTypes';

/** A fresh credential-free optional-panel read for non-LLM page controls. */
export function disabledLLMSettings(): LLMSettings {
  return {
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
      max_output_chars: 8192,
      max_tokens: 1024,
    },
    last_test: null,
  };
}
