import { afterEach, expect, test } from 'vitest';
import { errorFrom } from '../src/api/errors';
import { errorText, setLocale } from '../src/i18n';

afterEach(() => setLocale('en'));

test('known artifact failures stay failures and follow either interface language', () => {
  const detail = 'Run artifact contains invalid JSON.';
  const failure = errorFrom(422, { error: { code: 'invalid_artifact', message: detail } });
  expect(failure.code).toBe('invalid_artifact');
  expect(failure.status).toBe(422);
  expect(failure.uncertain).toBe(false);
  setLocale('zh-CN');
  expect(errorText(failure)).toBe('任务文件格式异常，结果尚不可用。');
  setLocale('en');
  expect(errorText(failure)).toBe('The task artifact is invalid; results are not available.');
  expect(failure.values.detail).toBe(detail);
});

test('unknown original messages and identifiers are not translated or rewritten', () => {
  const original = 'Compound I-07: IC50 < 0.21 nM';
  const failure = errorFrom(422, { error: { code: 'unknown_source_detail', message: original } });
  for (const locale of ['zh-CN', 'en'] as const) {
    setLocale(locale);
    expect(errorText(failure)).toBe(original);
  }
});

test('diagnostic detail retains the existing bound and is not normal banner copy', () => {
  const detail = 'CONTROLLED-DETAIL '.repeat(200);
  const failure = errorFrom(422, { error: { code: 'invalid_artifact', message: detail } });
  expect(failure.values.detail).toBe(detail.slice(0, 1000));
  setLocale('en');
  expect(errorText(failure)).not.toContain('CONTROLLED-DETAIL');
});
