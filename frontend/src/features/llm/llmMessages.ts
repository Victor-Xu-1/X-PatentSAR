import { ApiError } from '../../api/errors';
import type { LLMStatus, LLMTestReason } from '../../api/llmTypes';
import type { JobLLMRecovery } from '../../api/types';

export const llmStatusLabels: Record<LLMStatus, string> = {
  disabled: '已关闭',
  incomplete: '配置未完成',
  ready: '已配置',
};

// Server reasons are machine evidence, not a safe free-text display channel.
const testReasons: Record<LLMTestReason, string> = {
  nonce_verified: '随机验证样本校验通过。',
  invalid_response: '接口未正确返回随机验证样本，请检查协议及 JSON 响应格式。',
  transport_unavailable: '无法完成接口请求，请检查服务地址、网络及服务状态。',
  settings_changed: '测试期间配置或授权已改变，请刷新核对后再明确测试。',
  input_budget: '合成测试超出输入预算，请联系维护者核对调用限制。',
  authentication_failed: '接口认证失败，请检查已保存密钥及其模型访问权限。',
  rate_limited: '接口限流或额度不足，请核对服务商额度并稍后手动测试。',
  provider_unavailable: '外部服务暂不可用，请检查服务商状态并稍后手动测试。',
  timeout: '接口请求超时，请检查网络及服务状态，核对后再手动测试。',
  cancelled: '接口测试已取消，未取得有效验证结果。',
  cache_unavailable: '私有缓存不可用，请联系维护者检查存储及权限。',
  unsafe_cache: '私有缓存未通过安全检查，请联系维护者核对；不要删除缓存以绕过检查。',
};
const reasons: Record<string, string> = {
  ...testReasons,
  missing_endpoint: '尚未配置 API 地址。',
  missing_model: '尚未配置模型。',
  missing_key: '尚未配置密钥。',
  missing_consent: '尚未同意发送局部文字。',
  consent_required: '需要明确同意发送局部文字。',
  provider_rejected: '外部接口拒绝请求，请检查配置。',
  invalid_response: '接口返回格式未通过校验，请检查协议及 JSON 响应格式。',
  rate_limited: '接口限流或额度不足，请核对服务商额度并稍后手动恢复。',
  provider_unavailable: '外部服务暂不可用，请检查服务商状态并稍后手动恢复。',
  timeout: '接口请求超时，请检查网络及服务状态后再操作。',
  cancelled: '接口请求已取消，未取得有效结果。',
  network_error: '无法连接接口。',
  authorization_revoked: '此任务的 API 授权已撤回，请核对设置后明确更新授权。',
  credentials_changed: '已保存凭据已改变，请核对设置后明确更新此任务授权。',
  budget_exhausted: '此任务的调用预算已耗尽；更新授权不会重置配额。',
  invalid_evidence_selection: '接口的证据回答不合法，未采用该回答；请核对原始证据与接口响应格式。',
  control_unavailable: '授权控制状态不可用，请联系维护者核对；不会绕过授权继续调用。',
  carrier_error: '传输进程启动或清理失败，请联系维护者核对；不会自动重试。',
  configuration_unavailable: '已保存的 API 配置不可用，请在环境管理中核对配置。',
  redirect_rejected: '接口重定向已被拒绝，请核对直接服务地址；不会跟随重定向。',
  http_error: '接口返回 HTTP 错误，请核对服务地址、权限和服务状态。',
  call_budget: '此任务的调用预算已耗尽；更新授权不会重置配额。',
};

export const llmRecoveryStatusLabels: Record<JobLLMRecovery['status'], string> = {
  disabled: '局部修复已关闭',
  ready: '可尝试局部修复',
  blocked: '局部修复受阻',
  cooldown: '局部修复等待重试',
  exhausted: '局部修复预算耗尽',
  unavailable: '局部修复状态不可用',
};

export function llmAuthorizationError(error: unknown): Error {
  if (error instanceof ApiError) {
    if (error.uncertain || error.status >= 500)
      return new Error('授权写入结果尚未确认。请先刷新核对任务和配置，不要重复提交。');
    if (error.status === 409)
      return new Error('任务、配置或授权已改变。请先刷新核对，不会自动重试授权。');
    if (error.status === 404) return new Error('当前任务或 API 授权接口不可用，请刷新核对。');
    if (error.status === 422)
      return new Error('授权未被接受。请核对任务与已保存的相同服务、模型和协议。');
    if (error.status === 401 || error.status === 403)
      return new Error('会话或操作权限已失效，请重新加载页面。');
  }
  return new Error('授权未能确认。请刷新核对任务和配置后再操作。');
}

export function llmReason(reason: string | null): string | null {
  return reason === null
    ? null
    : Object.hasOwn(reasons, reason)
      ? reasons[reason]!
      : '请检查配置或联系服务维护者。';
}

export function llmTestReason(reason: string): string {
  return Object.hasOwn(testReasons, reason)
    ? testReasons[reason as LLMTestReason]
    : (llmReason(reason) ?? '请核对接口配置。');
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
