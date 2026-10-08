import { useState } from 'react';
import type { LLMApi } from '../../api/llmApi';
import { Dialog } from '../../components/Dialog';
import { ErrorNotice } from '../../components/Feedback';
import { LLMSettingsForm } from './LLMSettingsForm';
import { LLMTestConfirmation } from './LLMTestConfirmation';
import { llmStatusLabels } from './llmMessages';
import { useLLMSettings } from './useLLMSettings';
import '../../styles/llm.css';

export function LLMApiPanel({ api }: { api?: LLMApi }) {
  const controller = useLLMSettings(api);
  const [confirming, setConfirming] = useState(false);
  const { settings, readError, loading } = controller;
  const status = loading
    ? '正在读取…'
    : readError
      ? '无法读取'
      : settings
        ? llmStatusLabels[settings.status]
        : '尚未读取';
  return (
    <section className="llm-api-panel" aria-label="LLM API">
      <div className="llm-api-row">
        <div className="llm-api-heading">
          <h2>LLM API</h2>
          <output
            className={`llm-api-status${!loading && !readError && settings ? ` llm-status-${settings.status}` : ''}`}
            aria-label="LLM API 状态"
            aria-live="polite"
          >
            {status}
          </output>
          <p className="muted">仅外部 API，不在本机部署模型</p>
        </div>
        <button
          type="button"
          disabled={!settings || controller.unavailable || controller.busy}
          onClick={controller.openDialog}
        >
          配置
        </button>
      </div>
      {readError && !controller.open && (
        <ErrorNotice error={readError} onRetry={() => void controller.refresh()} />
      )}
      {controller.needsRefresh && !controller.open && !readError && (
        <ErrorNotice
          error={new Error('上次请求结果尚未确认。请先读取服务器状态。')}
          onRetry={() => void controller.refresh()}
        />
      )}
      {controller.open && (
        <Dialog
          title="LLM API 设置"
          busy={controller.busy || confirming}
          onClose={controller.close}
          className="llm-settings-dialog"
        >
          <LLMSettingsForm
            controller={controller}
            confirming={confirming}
            onTest={() => {
              if (controller.canTest) setConfirming(true);
            }}
          />
          {confirming && (
            <LLMTestConfirmation
              busy={controller.busy}
              onClose={() => {
                if (!controller.busy) setConfirming(false);
              }}
              onConfirm={() => {
                if (controller.canTest) void controller.test().finally(() => setConfirming(false));
              }}
            />
          )}
        </Dialog>
      )}
    </section>
  );
}
