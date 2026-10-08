import { useTranslation } from '../../i18n';
import type { LLMProtocol, LLMResponseMode } from '../../api/llmTypes';
import type { LLMDraft } from './llmDraft';

export function LLMProtocolFields({
  draft,
  onChange,
}: {
  draft: LLMDraft;
  onChange: (update: Partial<LLMDraft>) => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      <label className="form-field">
        {t('API 协议')}
        <select
          aria-label={t('API 协议')}
          value={draft.protocol}
          onChange={(event) => onChange({ protocol: event.target.value as LLMProtocol })}
        >
          <option value="openai-compatible">{t('OpenAI 兼容')}</option>
          <option value="anthropic">Anthropic</option>
          <option value="gemini">Gemini</option>
        </select>
      </label>
      {draft.protocol === 'openai-compatible' && (
        <details className="llm-limits">
          <summary>{t('响应格式')}</summary>
          <label className="form-field">
            {t('JSON 格式')}
            <select
              aria-label={t('JSON 格式')}
              value={draft.responseMode}
              onChange={(event) =>
                onChange({ responseMode: event.target.value as LLMResponseMode })
              }
            >
              <option value="json-schema">{t('严格 JSON Schema')}</option>
              <option value="json-object">{t('JSON 模式')}</option>
              <option value="prompt-only">{t('仅提示词 JSON')}</option>
            </select>
          </label>
        </details>
      )}
    </>
  );
}
