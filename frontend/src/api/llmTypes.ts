export type LLMMode = 'off' | 'on-error' | 'quality';
export type LLMStatus = 'disabled' | 'incomplete' | 'ready';
export type LLMProtocol = 'openai-compatible' | 'anthropic' | 'gemini';
export type LLMResponseMode = 'json-schema' | 'json-object' | 'prompt-only';

export interface LLMLimits {
  max_calls: number;
  timeout_seconds: number;
  max_input_chars: number;
  max_output_chars: number;
  max_tokens: number;
}

export interface LLMTestResult {
  status: 'passed' | 'failed';
  reason: string;
  settings_revision: number;
  checked_at: string;
}

/** A credential-free projection. The server never returns a saved key. */
export interface LLMSettings {
  revision: number;
  endpoint: string;
  model: string;
  protocol: LLMProtocol;
  response_mode: LLMResponseMode;
  mode: LLMMode;
  data_consent: boolean;
  key_configured: boolean;
  editable: boolean;
  status: LLMStatus;
  reason: string | null;
  limits: LLMLimits;
  last_test: LLMTestResult | null;
}

export interface LLMSettingsUpdate {
  expected_revision: number;
  endpoint: string;
  model: string;
  protocol: LLMProtocol;
  response_mode: LLMResponseMode;
  mode: LLMMode;
  data_consent: boolean;
  /** Omitted retains; the empty string explicitly clears. Write-only. */
  api_key?: string;
}
