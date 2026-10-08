import type { LLMProtocol, LLMResponseMode } from '../../api/llmTypes';
import type { LLMDraft } from './llmDraft';

export function LLMProtocolFields({
  draft,
  onChange,
}: {
  draft: LLMDraft;
  onChange: (update: Partial<LLMDraft>) => void;
}) {
  return (
    <>
      <label className="form-field">
        API 协议
        <select
          value={draft.protocol}
          onChange={(event) => onChange({ protocol: event.target.value as LLMProtocol })}
        >
          <option value="openai-compatible">OpenAI 兼容</option>
          <option value="anthropic">Anthropic</option>
          <option value="gemini">Gemini</option>
        </select>
      </label>
      {draft.protocol === 'openai-compatible' && (
        <details className="llm-limits">
          <summary>响应格式</summary>
          <label className="form-field">
            JSON 格式
            <select
              value={draft.responseMode}
              onChange={(event) =>
                onChange({ responseMode: event.target.value as LLMResponseMode })
              }
            >
              <option value="json-schema">严格 JSON Schema</option>
              <option value="json-object">JSON 模式</option>
              <option value="prompt-only">仅提示词 JSON</option>
            </select>
          </label>
        </details>
      )}
    </>
  );
}
