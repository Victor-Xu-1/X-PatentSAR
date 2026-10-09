import { expect, it } from 'vitest';
import { ApiError } from '../src/api/errors';
import { UiError, formatMessage } from '../src/i18n';
import { editorErrorSource } from '../src/features/structure-editor/editorErrorSource';

it('localizes client-generated drawing transport errors while preserving SDK/server diagnostics', () => {
  const source = '连接中断，写入结果未知。请先刷新状态，再决定是否重新提交。';
  const error = new ApiError(0, 'network_error', source, true);
  expect(editorErrorSource(error)).toEqual({ source });
  expect(formatMessage(editorErrorSource(error).source!, {}, 'en')).not.toContain('连接中断');
  expect(formatMessage(editorErrorSource(error).source!, {}, 'zh-CN')).toBe(source);
  expect(editorErrorSource(new UiError('绘图操作失败，请重新加载编辑器。'))).toHaveProperty(
    'source',
  );
  expect(editorErrorSource(new ApiError(422, 'chemical_validation', '原文结构诊断'))).toEqual({});
  expect(editorErrorSource(new Error('Native SDK diagnostic'))).toEqual({});
  expect(error.uncertain).toBe(true);
});
