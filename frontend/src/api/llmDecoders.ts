import type { Decoder } from './validation';
import { boolean, ContractError, count, object, oneOf, positive, string } from './validation';
import type { LLMSettings, LLMTestResult } from './llmTypes';

export function hasLLMControlCharacters(value: string): boolean {
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code < 32 || code === 127) return true;
  }
  return false;
}

function boundedString(max: number): Decoder<string> {
  return (value, path = '$') => {
    const result = string(value, path);
    if (result.length > max || hasLLMControlCharacters(result)) throw new ContractError(path);
    return result;
  };
}

function strictObject<T extends Record<string, Decoder<unknown>>>(shape: T) {
  const decode = object(shape);
  return (input: unknown, path = '$'): ReturnType<typeof decode> => {
    if (typeof input !== 'object' || input === null || Array.isArray(input))
      throw new ContractError(path);
    const keys = Object.keys(input);
    if (keys.length !== Object.keys(shape).length || keys.some((key) => !Object.hasOwn(shape, key)))
      // Do not include an unexpected field name/value (possibly a key) in errors.
      throw new ContractError(path);
    return decode(input, path);
  };
}

function explicitNullable<T>(decode: Decoder<T>): Decoder<T | null> {
  return (value, path) => (value === null ? null : decode(value, path));
}

/** No credentials, query parameters or fragments may be embedded in an API URL. */
export function validLLMEndpoint(value: string): boolean {
  if (value !== value.trim() || value.length > 2048 || /[\s\\?#]/u.test(value)) return false;
  try {
    const url = new URL(value);
    return (
      value.startsWith('https://') &&
      url.protocol === 'https:' &&
      Boolean(url.hostname) &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash
    );
  } catch {
    return false;
  }
}

const timestamp: Decoder<string> = (value, path = '$') => {
  const result = boundedString(64)(value, path);
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/u.test(result) ||
    !Number.isFinite(Date.parse(result))
  )
    throw new ContractError(path);
  return result;
};

export const decodeLLMTestResult: Decoder<LLMTestResult> = strictObject({
  status: oneOf(['passed', 'failed']),
  reason: boundedString(1000),
  settings_revision: count,
  checked_at: timestamp,
});

const settingsShape = strictObject({
  revision: count,
  endpoint: boundedString(2048),
  model: boundedString(256),
  protocol: oneOf(['openai-compatible', 'anthropic', 'gemini']),
  response_mode: oneOf(['json-schema', 'json-object', 'prompt-only']),
  mode: oneOf(['off', 'on-error', 'quality']),
  data_consent: boolean,
  key_configured: boolean,
  editable: boolean,
  status: oneOf(['disabled', 'incomplete', 'ready']),
  reason: explicitNullable(boundedString(1000)),
  limits: strictObject({
    max_calls: positive,
    timeout_seconds: positive,
    max_input_chars: positive,
    max_output_chars: positive,
    max_tokens: positive,
  }),
  last_test: explicitNullable(decodeLLMTestResult),
});

export const decodeLLMSettings: Decoder<LLMSettings> = (input, path = '$') => {
  const result = settingsShape(input, path);
  if (
    (result.endpoint !== '' && !validLLMEndpoint(result.endpoint)) ||
    (result.mode === 'off') !== (result.status === 'disabled') ||
    (result.status === 'ready' &&
      (!result.endpoint ||
        !result.model.trim() ||
        !result.key_configured ||
        !result.data_consent)) ||
    (result.last_test !== null && result.last_test.settings_revision > result.revision)
  )
    throw new ContractError(path);
  return result;
};
