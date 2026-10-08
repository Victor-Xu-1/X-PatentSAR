import { ApiError } from '../../api/errors';
import type { LLMStatus } from '../../api/llmTypes';

export const llmStatusLabels: Record<LLMStatus, string> = {
  disabled: '已关闭',
  incomplete: '配置未完成',
  ready: '已配置',
};

// Server reasons are machine evidence, not a safe free-text display channel.
const reasons: Record<string, string> = {
  missing_endpoint: '尚未配置 API 地址。',
  missing_model: '尚未配置模型。',
  missing_key: '尚未配置密钥。',
  missing_consent: '尚未同意发送局部文字。',
  consent_required: '需要明确同意发送局部文字。',
  authentication_failed: '接口认证失败，请检查密钥。',
  provider_rejected: '外部接口拒绝请求，请检查配置。',
  timeout: '接口请求超时。',
  invalid_response: '接口返回格式无效。',
  network_error: '无法连接接口。',
};

export function llmReason(reason: string | null): string | null {
  return reason === null
    ? null
    : Object.hasOwn(reasons, reason)
      ? reasons[reason]!
      : '请检查配置或联系服务维护者。';
}

export function llmRequestError(error: unknown, write = false): Error {
  if (error instanceof ApiError) {
    if (error.uncertain || (write && error.status >= 500))
      return new Error('请求结果尚未确认。请先刷新服务器状态，不要重复提交。');
    if (error.status === 409) return new Error('服务器配置已改变。请先刷新，再确认保留的输入。');
    if (error.status === 401 || error.status === 403)
      return new Error('会话或操作权限已失效，请重新加载页面。');
    if (error.status === 404) return new Error('当前后端尚未提供 LLM API 设置。');
    if (error.status === 422) return new Error('配置未被接受，请检查地址、模型、密钥和发送同意。');
  }
  return new Error(write ? '操作失败，请核对服务器状态后再操作。' : '无法读取 LLM API 设置。');
}
