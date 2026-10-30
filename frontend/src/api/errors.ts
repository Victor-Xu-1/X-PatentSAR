import { UiError } from '../i18n';
import type { MessageValues } from '../i18n';

export class ApiError extends UiError {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public uncertain = false,
    values: MessageValues = {},
  ) {
    super(message, values);
    this.name = 'ApiError';
  }
}
export function errorFrom(status: number, input: unknown): ApiError {
  if (typeof input === 'object' && input !== null && 'error' in input) {
    const error = input.error;
    if (
      typeof error === 'object' &&
      error !== null &&
      'code' in error &&
      'message' in error &&
      typeof error.code === 'string' &&
      typeof error.message === 'string'
    ) {
      const detail = error.message.slice(0, 1000);
      if (error.code === 'invalid_artifact') {
        return new ApiError(status, error.code, '任务文件格式异常，结果尚不可用。', false, {
          detail,
        });
      }
      return new ApiError(status, error.code, detail);
    }
  }
  return new ApiError(
    status,
    'http_error',
    '服务请求失败（HTTP {status}）。请稍后重试或检查服务状态。',
    false,
    { status },
  );
}
