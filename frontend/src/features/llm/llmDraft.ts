import { hasLLMControlCharacters, validLLMEndpoint } from '../../api/llmDecoders';
import type {
  LLMMode,
  LLMProtocol,
  LLMResponseMode,
  LLMSettings,
  LLMSettingsUpdate,
} from '../../api/llmTypes';

export interface LLMDraft {
  endpoint: string;
  model: string;
  protocol: LLMProtocol;
  responseMode: LLMResponseMode;
  mode: LLMMode;
  dataConsent: boolean;
  apiKey: string;
  clearKey: boolean;
}

export function llmDraft(settings: LLMSettings): LLMDraft {
  return {
    endpoint: settings.endpoint,
    model: settings.model,
    protocol: settings.protocol,
    responseMode: settings.response_mode,
    mode: settings.mode,
    dataConsent: settings.data_consent,
    apiKey: '',
    clearKey: false,
  };
}

export function sameLLMConfig(draft: LLMDraft, settings: LLMSettings): boolean {
  return (
    draft.endpoint.trim() === settings.endpoint &&
    draft.model.trim() === settings.model &&
    draft.protocol === settings.protocol &&
    draft.responseMode === settings.response_mode &&
    draft.mode === settings.mode &&
    draft.dataConsent === settings.data_consent
  );
}

export function dirtyLLMDraft(draft: LLMDraft, base: LLMSettings): boolean {
  return !sameLLMConfig(draft, base) || draft.apiKey !== '' || draft.clearKey;
}

export function updateLLMDraft(draft: LLMDraft, update: Partial<LLMDraft>): LLMDraft {
  if (update.clearKey === true)
    return { ...draft, ...update, mode: 'off', dataConsent: false, apiKey: '', clearKey: true };
  const identityChanged =
    (update.endpoint !== undefined && update.endpoint.trim() !== draft.endpoint.trim()) ||
    (update.model !== undefined && update.model.trim() !== draft.model.trim()) ||
    (update.protocol !== undefined && update.protocol !== draft.protocol);
  return {
    ...draft,
    ...update,
    ...(update.mode === 'off' ? { dataConsent: false } : {}),
    ...(identityChanged ? { apiKey: '' } : {}),
    ...(update.protocol && update.protocol !== 'openai-compatible'
      ? { responseMode: 'json-schema' as const }
      : {}),
  };
}

export function llmSaveRequest(draft: LLMDraft, base: LLMSettings): LLMSettingsUpdate {
  const endpoint = draft.endpoint.trim();
  const model = draft.model.trim();
  if (endpoint && !validLLMEndpoint(endpoint))
    throw new Error('请输入 HTTPS API 基础地址，不得包含凭据、查询参数或片段。');
  if (model.length > 128 || hasLLMControlCharacters(model)) throw new Error('模型名称无效。');
  if (
    draft.apiKey.length > 4096 ||
    hasLLMControlCharacters(draft.apiKey) ||
    (draft.apiKey && /\s/u.test(draft.apiKey))
  )
    throw new Error('密钥格式无效，请重新输入。');
  const identityChanged =
    endpoint !== base.endpoint || model !== base.model || draft.protocol !== base.protocol;
  if (identityChanged && !draft.apiKey && !draft.clearKey)
    throw new Error('地址、模型或协议已改变，请输入新密钥，或明确清除密钥并关闭。');
  if (draft.mode !== 'off') {
    if (!draft.dataConsent) throw new Error('启用前请明确同意发送有限局部文字。');
    if (!endpoint || !model || draft.clearKey || (!draft.apiKey && !base.key_configured))
      throw new Error('启用前请填写 API 地址、模型和密钥。');
  }
  return {
    expected_revision: base.revision,
    endpoint,
    model,
    protocol: draft.protocol,
    response_mode: draft.protocol === 'openai-compatible' ? draft.responseMode : 'json-schema',
    mode: draft.mode,
    data_consent: draft.mode === 'off' ? false : draft.dataConsent,
    ...(draft.clearKey ? { api_key: '' } : draft.apiKey ? { api_key: draft.apiKey } : {}),
  };
}
