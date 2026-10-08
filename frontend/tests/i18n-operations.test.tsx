import { describe, expect, it, vi } from 'vitest';
import { combineCatalogs } from '../src/i18n/catalogMerge';
import { common } from '../src/i18n/catalogs/common';
import { operations } from '../src/i18n/catalogs/operations';
import { jobs } from '../src/i18n/catalogs/jobs';
import { environment } from '../src/i18n/catalogs/environment';
import { llm } from '../src/i18n/catalogs/llm';
import { history } from '../src/i18n/catalogs/history';
import { t } from '../src/i18n';
import { storageLocationFields } from '../src/features/environment/storageLocations';
import { llmStatusLabels } from '../src/features/llm/llmMessages';
import { stageLabels } from '../src/model/presentation';
import { setupOperationsLocale, switchTo } from './i18n-operations-fixtures';

setupOperationsLocale();

describe('operations locale: catalogs and default preference', () => {
  it('assembles every feature catalog once with common captions at their canonical authority', () => {
    const catalogs = [jobs, environment, llm, history];
    const sources = catalogs.flatMap(Object.keys);
    expect(new Set(sources).size).toBe(sources.length);
    expect(Object.keys(operations).sort()).toEqual([...sources].sort());
    expect(operations).toEqual(combineCatalogs(...catalogs));
    for (const [source, english] of Object.entries({
      任务记录: 'Tasks',
      环境管理: 'Environment',
      'LLM API 设置': 'LLM API settings',
      复核模式: 'Review mode',
      配置: 'Configure',
      保存: 'Save',
      关闭对话框: 'Close dialog',
    }))
      expect(t(source), source).toBe(english);
    expect(jobs).not.toHaveProperty('回收站');
    expect(history).not.toHaveProperty('已生成文件');
  });

  it('keeps catalog placeholders exact and exported source labels locale-independent', () => {
    expect(() => combineCatalogs(common, operations)).not.toThrow();
    const placeholders = (value: string) =>
      [...value.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map((match) => match[1]).sort();
    for (const [source, english] of Object.entries(operations)) {
      expect(english, source).not.toMatch(/[\u3400-\u9fff]/u);
      expect(placeholders(english), source).toEqual(placeholders(source));
    }
    switchTo('en');
    expect(stageLabels.classify).toBe('文档解析');
    expect(llmStatusLabels.ready).toBe('已配置');
    expect(storageLocationFields[0].label).toBe('集成环境安装目录');
    expect(t(stageLabels.classify)).toBe('Document parsing');
  });

  it.each([null, '', 'unsupported-locale'])(
    'uses English for a fresh operations import with saved preference %s',
    async (saved) => {
      if (saved === null) localStorage.removeItem('x-patentsar.locale');
      else localStorage.setItem('x-patentsar.locale', saved);
      vi.resetModules();
      const fresh = await import('../src/i18n');
      expect(fresh.getLocale()).toBe('en');
      expect(fresh.t('任务记录')).toBe('Tasks');
      expect(fresh.t('环境管理')).toBe('Environment');
      expect(document.documentElement.lang).toBe('en');
    },
  );
});
