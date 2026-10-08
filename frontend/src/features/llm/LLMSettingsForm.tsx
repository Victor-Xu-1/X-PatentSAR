import { useId } from 'react';
import type { LLMMode } from '../../api/llmTypes';
import { ErrorNotice, Loading } from '../../components/Feedback';
import { llmReason } from './llmMessages';
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
      {!settings.editable && <p className="info-banner">配置由环境变量管理，网页只读。</p>}
      <p className="muted llm-field-note">
        设置变更仅影响后续新任务；续跑沿用原配置快照与剩余调用配额。
      </p>
      <fieldset className="llm-settings-fields" disabled={locked}>
        <legend className="sr-only">LLM API 配置</legend>
        <label className="form-field">
          HTTPS API 基础地址
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
          模型
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
            API 密钥
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
              ? '保存时清除密钥并关闭。'
              : settings.key_configured
                ? '已保存密钥；留空保留，不回显。'
                : '尚未保存密钥。'}
          </p>
          <label className="llm-checkbox">
            <input
              type="checkbox"
              checked={draft.clearKey}
              onChange={(event) => controller.update({ clearKey: event.target.checked })}
            />
            清除密钥并关闭
          </label>
        </div>
        <label className="form-field">
          复核模式
          <select
            aria-label="复核模式"
            value={draft.mode}
            aria-describedby={modeNoteId}
            onChange={(event) => controller.update({ mode: event.target.value as LLMMode })}
          >
            <option value="off">关闭（Off）</option>
            <option value="on-error">出错时复核（on-error）</option>
            <option value="quality">质量复核（quality）</option>
          </select>
        </label>
        <p id={modeNoteId} className="muted llm-field-note">
          关闭或撤回授权将停止外发；质量模式额外复核列映射。
        </p>
        <label className="llm-checkbox">
          <input
            type="checkbox"
            checked={draft.dataConsent}
            aria-describedby={consentId}
            onChange={(event) => controller.update({ dataConsent: event.target.checked })}
          />
          我同意向所选外部 API 发送有限的局部文字
        </label>
        <p id={consentId} className="muted llm-field-note">
          仅局部表头、位置和校验证据，不发送整份 PDF、分子图、SMILES 或全部数据行。
        </p>
      </fieldset>
      <details className="llm-limits">
        <summary>固定调用上限</summary>
        <p>
          每任务最多 {settings.limits.max_calls} 次 · 超时 {settings.limits.timeout_seconds} 秒 ·
          输入/输出 {settings.limits.max_input_chars}/{settings.limits.max_output_chars} 字符 · 输出{' '}
          {settings.limits.max_tokens} token
        </p>
      </details>
      {controller.loading && <Loading label="正在核对服务器设置…" />}
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
          刷新服务器状态
        </button>
      )}
      {controller.conflict && !controller.needsRefresh && !controller.readError && (
        <div className="conflict" role="alert">
          服务器设置已更新，未覆盖你的非密钥输入。请核对后继续；密钥需重新输入。
          <button
            type="button"
            disabled={controller.busy || controller.loading}
            onClick={controller.acceptRevision}
          >
            使用最新版本并保留输入
          </button>
        </div>
      )}
      {controller.saved && (
        <output className="llm-message" aria-live="polite">
          设置已保存。
        </output>
      )}
      {!controller.dirty && lastTest && (
        <output className="llm-message" aria-live="polite">
          {lastTest.status === 'passed'
            ? '接口测试通过。'
            : `接口测试失败。${llmReason(lastTest.reason) ?? ''}`}
        </output>
      )}
      {settings.status === 'incomplete' && !controller.dirty && (
        <p className="muted">{llmReason(settings.reason) ?? '请补全 API 配置。'}</p>
      )}
      {settings.status === 'ready' && (
        <div className="llm-test-action">
          <button type="button" disabled={!controller.canTest || confirming} onClick={onTest}>
            测试接口
          </button>
          {controller.dirty && <span className="muted">请先保存设置。</span>}
        </div>
      )}
      <footer className="dialog-actions">
        <button type="button" disabled={controller.busy || confirming} onClick={controller.close}>
          取消
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
          {controller.busy ? '处理中…' : '保存'}
        </button>
      </footer>
    </form>
  );
}
