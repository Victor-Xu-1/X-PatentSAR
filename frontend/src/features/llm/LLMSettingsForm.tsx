import { useTranslation } from '../../i18n';
import { useId } from 'react';
import type { LLMMode } from '../../api/llmTypes';
import { ErrorNotice, Loading } from '../../components/Feedback';
import { llmReason, llmTestReason } from './llmMessages';
import type { LLMSettingsController } from './useLLMSettings';
import { LLMProtocolFields } from './LLMProtocolFields';

export function LLMSettingsForm({
  controller,
  confirming,
  onTest,
}: {
  controller: LLMSettingsController;
  confirming: boolean;
  onTest: () => void;
}) {
  const { t } = useTranslation();
  const { settings, draft } = controller;
  const keyNoteId = useId();
  const consentId = useId();
  const modeNoteId = useId();
  if (!settings || !draft) return null;
  const locked = controller.busy || controller.loading || confirming || !settings.editable;
  const lastTest =
    settings.last_test?.settings_revision === settings.revision ? settings.last_test : null;
  return (
    <form
      className="dialog-body llm-settings-form"
      autoComplete="off"
      onSubmit={(event) => {
        event.preventDefault();
        if (!confirming) void controller.save();
      }}
    >
      {!settings.editable && <p className="info-banner">{t('配置由环境变量管理，网页只读。')}</p>}
      <p className="muted llm-field-note">
        {t('设置变更仅影响后续新任务；续跑沿用原配置快照与剩余调用配额。')}
      </p>
      <fieldset className="llm-settings-fields" disabled={locked}>
        <legend className="sr-only">{t('LLM API 配置')}</legend>
        <label className="form-field">
          {t('HTTPS API 基础地址')}
          <input
            type="text"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            maxLength={2048}
            placeholder="https://api.example.com/v1"
            value={draft.endpoint}
            data-initial-focus
            onChange={(event) => controller.update({ endpoint: event.target.value })}
          />
        </label>
        <label className="form-field">
          {t('模型')}
          <input
            type="text"
            autoComplete="off"
            spellCheck={false}
            maxLength={128}
            value={draft.model}
            onChange={(event) => controller.update({ model: event.target.value })}
          />
        </label>
        <LLMProtocolFields draft={draft} onChange={controller.update} />
        <div className="llm-key-field">
          <label className="form-field">
            {t('API 密钥')}
            <input
              type="password"
              autoComplete="new-password"
              spellCheck={false}
              maxLength={4096}
              value={draft.apiKey}
              disabled={draft.clearKey}
              aria-describedby={keyNoteId}
              onChange={(event) => controller.update({ apiKey: event.target.value })}
            />
          </label>
          <p id={keyNoteId} className="muted">
            {draft.clearKey
              ? t('保存时清除密钥并关闭。')
              : settings.key_configured
                ? t('已保存密钥；留空保留，不回显。')
                : t('尚未保存密钥。')}
          </p>
          <label className="llm-checkbox">
            <input
              type="checkbox"
              checked={draft.clearKey}
              onChange={(event) => controller.update({ clearKey: event.target.checked })}
            />
            {t('清除密钥并关闭')}
          </label>
        </div>
        <label className="form-field">
          {t('复核模式')}
          <select
            aria-label={t('复核模式')}
            value={draft.mode}
            aria-describedby={modeNoteId}
            onChange={(event) => controller.update({ mode: event.target.value as LLMMode })}
          >
            <option value="off">{t('关闭（Off）')}</option>
            <option value="on-error">{t('出错时复核（on-error）')}</option>
            <option value="quality">{t('质量复核（quality）')}</option>
          </select>
        </label>
        <p id={modeNoteId} className="muted llm-field-note">
          {t('关闭或撤回授权将停止外发；质量模式额外复核列映射。')}
        </p>
        <label className="llm-checkbox">
          <input
            type="checkbox"
            checked={draft.dataConsent}
            aria-describedby={consentId}
            onChange={(event) => controller.update({ dataConsent: event.target.checked })}
          />
          {t('我同意向所选外部 API 发送有限的局部文字')}
        </label>
        <p id={consentId} className="muted llm-field-note">
          {t('仅局部表头、位置和校验证据，不发送整份 PDF、分子图、SMILES 或全部数据行。')}
        </p>
      </fieldset>
      <details className="llm-limits">
        <summary>{t('固定调用上限')}</summary>
        <p>
          {t(
            '每任务最多 {calls} 次 · 超时 {seconds} 秒 · 输入/输出 {input}/{output} 字符 · 输出 {tokens} token',
            {
              calls: settings.limits.max_calls,
              seconds: settings.limits.timeout_seconds,
              input: settings.limits.max_input_chars,
              output: settings.limits.max_output_chars,
              tokens: settings.limits.max_tokens,
            },
          )}
        </p>
      </details>
      {controller.loading && <Loading label={t('正在核对服务器设置…')} />}
      {controller.readError && (
        <ErrorNotice error={controller.readError} onRetry={() => void controller.refresh()} />
      )}
      {controller.error && <ErrorNotice error={controller.error} />}
      {controller.needsRefresh && (
        <button
          type="button"
          disabled={controller.busy || controller.loading}
          onClick={() => void controller.refresh()}
        >
          {t('刷新服务器状态')}
        </button>
      )}
      {controller.conflict && !controller.needsRefresh && !controller.readError && (
        <div className="conflict" role="alert">
          {t('服务器设置已更新，未覆盖你的非密钥输入。请核对后继续；密钥需重新输入。')}
          <button
            type="button"
            disabled={controller.busy || controller.loading}
            onClick={controller.acceptRevision}
          >
            {t('使用最新版本并保留输入')}
          </button>
        </div>
      )}
      {controller.saved && (
        <output className="llm-message" aria-live="polite">
          {t('设置已保存。')}
        </output>
      )}
      {!controller.dirty && lastTest && (
        <output className="llm-message" aria-live="polite">
          {lastTest.status === 'passed'
            ? t('接口测试通过。')
            : t('接口测试失败。{reason}', { reason: llmTestReason(lastTest.reason) })}
        </output>
      )}
      {settings.status === 'ready' && (
        <p className="muted llm-field-note">
          {t('已配置不等于模型可用；接口测试只校验随机合成样本，不代表真实模型提取或科学验收。')}
        </p>
      )}
      {settings.status === 'incomplete' && !controller.dirty && (
        <p className="muted">{llmReason(settings.reason) ?? t('请补全 API 配置。')}</p>
      )}
      {settings.status === 'ready' && (
        <div className="llm-test-action">
          <button type="button" disabled={!controller.canTest || confirming} onClick={onTest}>
            {t('测试接口')}
          </button>
          {controller.dirty && <span className="muted">{t('请先保存设置。')}</span>}
        </div>
      )}
      <footer className="dialog-actions">
        <button type="button" disabled={controller.busy || confirming} onClick={controller.close}>
          {t('取消')}
        </button>
        <button
          type="submit"
          className="primary"
          disabled={
            locked ||
            controller.unavailable ||
            !controller.dirty ||
            (draft.mode !== 'off' && !draft.dataConsent)
          }
        >
          {controller.busy ? t('处理中…') : t('保存')}
        </button>
      </footer>
    </form>
  );
}
