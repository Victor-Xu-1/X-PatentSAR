import { describe, expect, it } from 'vitest';
import { parseRoute, routeHash } from '../src/model/route';
import { activityText, dateText } from '../src/model/presentation';
import { validatePdf, maxPdfSize } from '../src/model/uploads';
import {
  decodeCompound,
  decodeHealth,
  decodeJob,
  decodePage,
  decodeProject,
} from '../src/api/decoders';
import { safeAssetUrl } from '../src/api';
import { compound, health, job, page, project } from './fixtures';

describe('routes and presentation', () => {
  it('preserves measured ranges without appending a duplicate unit', () => {
    const activity = {
      name: 'DC50 (nM)',
      value: '10 - 100 nM',
      unit: 'nM',
      target: null,
      assay: null,
      page: null,
    };
    expect(activityText(activity)).toBe('DC50 (nM) = 10 - 100 nM');
    expect(activityText({ ...activity, value: '<1 nM' })).toBe('DC50 (nM) = <1 nM');
    expect(activityText({ ...activity, value: 0 })).toBe('DC50 (nM) = 0 nM');
    expect(activityText({ ...activity, value: '1 nM', unit: 'M' })).toBe('DC50 (nM) = 1 nM M');
    expect(activity.value).toBe('10 - 100 nM');
  });
  it('preserves workspace, page, tab and source selection in refreshable links', () => {
    const route = {
      view: 'workspace' as const,
      projectId: 'a/b 空格',
      page: 8,
      tab: 'annotations' as const,
      compoundId: 'I-7',
    };
    expect(parseRoute(routeHash(route))).toEqual(route);
  });
  it.each(['0', '-5', 'NaN', 'Infinity', '1.2'])('bounds invalid page %s', (value) =>
    expect(parseRoute(`#/projects/id?page=${value}`).page).toBeNull(),
  );
  it('handles malformed URL encoding and management pages', () => {
    expect(parseRoute('#/projects/%ZZ').projectId).toBeNull();
    expect(parseRoute('#/jobs').view).toBe('jobs');
    expect(parseRoute('#/settings').view).toBe('settings');
  });
  it('preserves grade activities and missing values, without inventing IC50', () => {
    expect(activityText(compound.activities[0]!)).toBe('抑制等级 = ++');
    expect(activityText({ ...compound.activities[0]!, value: null })).toContain('值未提供');
    expect(dateText(null)).toBe('—');
  });
});
describe('untrusted API inputs', () => {
  it('does not accept another product or unsupported web protocol on a shared port', () => {
    expect(() =>
      decodeHealth({ ...health, product: { ...health.product, name: 'OtherApp' } }),
    ).toThrow('契约');
    expect(() => decodeHealth({ ...health, schema: { ...health.schema, version: 2 } })).toThrow(
      '契约',
    );
  });
  it('accepts null page geometry when historical original PDF is absent', () => {
    const historical = {
      ...page,
      width: null,
      height: null,
      image_url: null,
      source_mode: 'historical',
    };
    expect(decodePage(historical)).toEqual(historical);
  });
  it('parses the current contract without upgrading historical confidence', () => {
    expect(decodeCompound(compound).confidence).toEqual({
      level: 'unknown',
      score: null,
      reason: '历史契约证据',
    });
    expect(decodeProject(project)).toEqual(project);
    expect(decodePage(page)).toEqual(page);
    expect(decodeJob(job)).toEqual(job);
  });
  it.each([NaN, Infinity, -1, 1.2])('rejects invalid counter %s', (value) =>
    expect(() =>
      decodeProject({ ...project, summary: { ...project.summary, structures: value } }),
    ).toThrow('契约'),
  );
  it('rejects malformed geometry, confidence and invented stage names', () => {
    expect(() =>
      decodeCompound({ ...compound, source: { ...compound.source, bbox: [8, 2, 1, 3] } }),
    ).toThrow('契约');
    expect(() =>
      decodeCompound({ ...compound, confidence: { ...compound.confidence, level: 'certain' } }),
    ).toThrow('契约');
    expect(() => decodeJob({ ...job, stages: [{ ...job.stages[0], name: 'admet' }] })).toThrow(
      '契约',
    );
  });
  it.each([
    'https://external.invalid/image',
    'javascript:alert(1)',
    'data:image/png;base64,x',
    '/api/v1/runtime',
    'http://[',
  ])('does not render unsafe asset URL %s', (url) => expect(safeAssetUrl(url)).toBeNull());
  it('accepts only same-origin contract image paths', () =>
    expect(safeAssetUrl(compound.structure_image_url)).toBe(compound.structure_image_url));
});
describe('raw PDF upload validation', () => {
  it('accepts a PDF header, leaving full parse to backend', async () =>
    await expect(validatePdf(new File(['%PDF-1.7\n'], 'source.pdf'))).resolves.toBeUndefined());
  it('rejects empty and renamed non-PDF content', async () => {
    await expect(validatePdf(new File([], 'empty.pdf'))).rejects.toThrow('为空');
    await expect(validatePdf(new File(['hello'], 'source.pdf'))).rejects.toThrow('文件头');
    await expect(validatePdf(new File(['%PDF-'], 'source.txt'))).rejects.toThrow('.pdf');
  });
  it('rejects oversize files before reading', async () => {
    const file = new File(['%PDF-'], 'large.pdf');
    Object.defineProperty(file, 'size', { value: maxPdfSize + 1 });
    await expect(validatePdf(file)).rejects.toThrow('128 MiB');
  });
});
