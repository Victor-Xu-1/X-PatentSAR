import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Header } from '../src/components/Header';
import { ErrorNotice } from '../src/components/Feedback';
import { NewTaskPage } from '../src/features/tasks/NewTaskPage';
import {
  errorText,
  getLocale,
  LOCALE_STORAGE_KEY,
  setLocale,
  t,
  UiError,
  DEFAULT_LOCALE,
  SUPPORTED_LANGUAGES,
} from '../src/i18n';
import { combineCatalogs, englishCatalog } from '../src/i18n/catalog';
import { api } from '../src/api';
import { ContractError } from '../src/api/validation';
import { ApiError } from '../src/api/errors';

afterEach(() => {
  setLocale('zh-CN');
  localStorage.removeItem(LOCALE_STORAGE_KEY);
  vi.restoreAllMocks();
});
beforeEach(() => setLocale(DEFAULT_LOCALE));

const header = (disabled = false) => (
  <Header
    view="new-task"
    project={null}
    version="0.1.5"
    onUpload={vi.fn()}
    onRecent={vi.fn()}
    onNavigate={vi.fn()}
    onAnalysis={vi.fn()}
    disabled={disabled}
  />
);

describe('one application-owned localization authority', () => {
  it('switches live navigation, accessible names, document language and its one preference', async () => {
    const user = userEvent.setup();
    render(header());
    expect(DEFAULT_LOCALE).toBe('en');
    expect(SUPPORTED_LANGUAGES.map((language) => language.id)).toEqual(
      expect.arrayContaining(['en', 'zh-CN']),
    );
    await user.selectOptions(screen.getByRole('combobox', { name: 'Interface language' }), 'zh-CN');
    await user.selectOptions(screen.getByRole('combobox', { name: '界面语言' }), 'en');
    expect(screen.getByRole('button', { name: 'Upload PDF' })).toBeVisible();
    expect(screen.getByRole('navigation', { name: 'Workspace navigation' })).toBeVisible();
    expect(screen.getByRole('combobox', { name: 'Interface language' })).toHaveValue('en');
    expect(document.documentElement.lang).toBe('en');
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('en');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Interface language' }), 'zh-CN');
    expect(screen.getByRole('button', { name: '上传 PDF' })).toBeVisible();
    expect(document.documentElement.lang).toBe('zh-CN');
  });

  it('keeps the language control usable while connection-dependent actions are disabled', async () => {
    render(header(true));
    const language = screen.getByRole('combobox', { name: 'Interface language' });
    expect(language).toBeEnabled();
    await userEvent.selectOptions(language, 'en');
    expect(screen.getByRole('button', { name: 'Upload PDF' })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Interface language' })).toBeEnabled();
  });

  it('preserves a usable session choice if browser preference storage is denied', () => {
    setLocale('zh-CN');
    const denied = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Denied', 'SecurityError');
    });
    expect(() => setLocale('en')).not.toThrow();
    expect(getLocale()).toBe('en');
    expect(document.documentElement.lang).toBe('en');
    denied.mockRestore();
  });

  it('ignores unsupported input without corrupting the current language', () => {
    setLocale('zh-CN');
    expect(() => setLocale('invalid' as never)).toThrow('Unsupported interface language');
    expect(getLocale()).toBe('zh-CN');
  });

  it('synchronizes only the local preference and resets removed or invalid preferences to English', () => {
    const change = (value: string | null, key: string | null = LOCALE_STORAGE_KEY) =>
      window.dispatchEvent(
        new StorageEvent('storage', { key, newValue: value, storageArea: localStorage }),
      );
    change('zh-CN');
    expect(getLocale()).toBe('zh-CN');
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: LOCALE_STORAGE_KEY,
        newValue: 'en',
        storageArea: sessionStorage,
      }),
    );
    expect(getLocale()).toBe('zh-CN');
    change('invalid');
    expect(getLocale()).toBe('en');
    change('zh-CN');
    change(null);
    expect(getLocale()).toBe('en');
    change('zh-CN');
    change(null, null);
    expect(getLocale()).toBe('en');
    expect(document.documentElement.lang).toBe('en');
  });

  it('localizes saved UI errors again when language changes, without changing error provenance', async () => {
    const error = new UiError('服务请求失败（HTTP {status}）。请稍后重试或检查服务状态。', {
      status: 409,
    });
    const before = error.message;
    render(<ErrorNotice error={error} />);
    await act(() => setLocale('en'));
    expect(screen.getByRole('alert')).toHaveTextContent('Server request failed');
    expect(errorText(error)).toContain('HTTP 409');
    expect(errorText(error)).toContain('Server request failed');
    expect(error.message).toBe(before);
    await act(() => setLocale('zh-CN'));
    expect(errorText(error)).toBe(before);
  });

  it('preserves identifiers, filenames, chemistry and unknown raw source strings', () => {
    setLocale('en');
    for (const source of [
      '中文专利原文.pdf',
      'Example 001-8B',
      'IC50 (nM)',
      '[13CH3][C@H](O)Cl',
      '原文实验活性值 <0.10 µM',
    ])
      expect(t(source)).toBe(source);
    expect(t('打开 {title}', { title: '中文专利原文.pdf' })).toBe('Open 中文专利原文.pdf');
  });

  it('rejects competing catalog meanings and keeps interpolation placeholders lossless', () => {
    expect(() => combineCatalogs({ 保存: 'Save' }, { 保存: 'Store' })).toThrow();
    expect(combineCatalogs({ 保存: 'Save' }, { 保存: 'Save' })).toEqual({ 保存: 'Save' });
    const fields = (value: string) =>
      [...value.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map((match) => match[1]).sort();
    for (const [source, english] of Object.entries(englishCatalog))
      expect(fields(english), source).toEqual(fields(source));
  });

  it('relocalizes nested contract diagnostics without changing uncertain-write semantics', () => {
    const detail = new ContractError('$.job.id');
    const error = new ApiError(
      200,
      'invalid_write_response',
      '服务已响应，但无法确认写入结果。请先检查已保存状态，不要盲目重新提交。{detail}',
      true,
      { detail },
    );
    const message = error.message;
    setLocale('en');
    expect(errorText(error)).toContain('API data does not match the contract ($.job.id)');
    expect(errorText(error)).not.toMatch(/[\u3400-\u9fff]/);
    expect(error.uncertain).toBe(true);
    expect(error.code).toBe('invalid_write_response');
    expect(error.message).toBe(message);
    setLocale('zh-CN');
    expect(errorText(error)).toBe(message);
  });

  it('does not remount PDF input or discard an existing selection, and makes no language API mutation', async () => {
    const upload = vi.spyOn(api, 'upload');
    const create = vi.spyOn(api, 'createJob');
    render(
      <>
        {header()}
        <NewTaskPage ready connected onCreated={vi.fn()} onOpen={vi.fn()} />
      </>,
    );
    const input = screen.getByLabelText('Original patent PDF file');
    const file = new File(['%PDF-synthetic-control'], '中文原文.pdf', { type: 'application/pdf' });
    await userEvent.upload(input, file);
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Interface language' }),
      'zh-CN',
    );
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '界面语言' }), 'en');
    expect(screen.getByLabelText('Original patent PDF file')).toBe(input);
    expect((input as HTMLInputElement).files?.[0]).toBe(file);
    expect(screen.getByText('中文原文.pdf')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Upload patent PDF' })).toBeVisible();
    expect(upload).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
  });
});
