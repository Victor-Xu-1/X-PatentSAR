import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { ApiError } from '../src/api/errors';
import { historyApi } from '../src/api/historyApi';
import { decodeHistoryEntry, decodeHistoryList } from '../src/api/historyDecoders';
import type { HistoryKind } from '../src/api/historyTypes';
import { ContractError } from '../src/api/validation';
import { json, session } from './fixtures';
import { historyEntry, historyList, trashed, historyProject, historyJob } from './history-fixtures';

describe('bounded recoverable history API v1 contract', () => {
  it('decodes all four kinds and preserves null/false instead of guessing permissions or size', () => {
    for (const kind of ['project', 'job', 'export', 'environment_operation'] as const) {
      const entry = historyEntry({ kind, can_delete: false });
      expect(decodeHistoryEntry(entry)).toEqual(entry);
    }
    expect(decodeHistoryList(historyList([]))).toEqual(historyList([]));
  });
  it.each([
    ['kind', 'file'],
    ['id', '../../private'],
    ['id', 'x'.repeat(65)],
    ['project_id', 'x'.repeat(33)],
    ['title', ''],
    ['title', '字'.repeat(251)],
    ['status', 'x'.repeat(41)],
    ['created_at', 'x'.repeat(81)],
    ['deleted_at', 0],
    ['revision', 'a'.repeat(63)],
    ['revision', 'A'.repeat(64)],
    ['can_delete', 'true'],
    ['can_restore', 1],
    ['blocked_reason', 'x'.repeat(301)],
    ['size_bytes', -1],
    ['size_bytes', 1.1],
    ['size_bytes', Infinity],
    ['size_bytes', NaN],
    ['size_bytes', Number.MAX_SAFE_INTEGER + 1],
  ])('rejects malformed %s rather than coercing it', (field, value) => {
    expect(() => decodeHistoryEntry({ ...historyEntry(), [field]: value })).toThrow(ContractError);
  });
  it('rejects oversized, duplicate and malformed pages', () => {
    for (const value of [
      historyList([], { page: 0 }),
      historyList([], { page_size: 101 }),
      historyList([], { total: -1 }),
      historyList([historyEntry()], { total: 0 }),
      historyList([historyEntry(), historyEntry()]),
      historyList(Array.from({ length: 101 }, (_, n) => historyEntry({ id: `item-${n}` }))),
    ])
      expect(() => decodeHistoryList(value)).toThrow(ContractError);
  });
  it('accepts exactly 100 unique bounded identities and zero-byte files', () => {
    const items = Array.from({ length: 100 }, (_, index) => {
      const id = index.toString(16).padStart(32, '0');
      return historyEntry({ id, project_id: id, size_bytes: 0 });
    });
    expect(decodeHistoryList(historyList(items, { page_size: 100 })).items).toHaveLength(100);
  });
  it('cross-validates kind-specific IDs, project identities and impossible permission states', () => {
    for (const entry of [
      historyEntry({ kind: 'export', id: historyProject.id }),
      historyEntry({ kind: 'job', id: 'a'.repeat(64) }),
      historyEntry({ kind: 'environment_operation', project_id: historyProject.id }),
      historyEntry({ project_id: '4'.repeat(32) }),
      historyEntry({ project_id: null }),
      historyEntry({ can_restore: true }),
      { ...trashed(historyEntry()), can_delete: true },
      {
        ...trashed(historyEntry({ kind: 'job' })),
        can_restore: true,
        blocked_reason: 'Restore parent first.',
      },
    ])
      expect(() => decodeHistoryEntry(entry)).toThrow(ContractError);
  });
  it('allows deleting an unavailable file record while still refusing unsupported restore permission', () => {
    const entry = historyEntry({
      kind: 'export',
      blocked_reason: 'Saved file unavailable for recovery.',
    });
    expect(decodeHistoryEntry(entry)).toEqual(entry);
    expect(() => decodeHistoryEntry({ ...trashed(entry), can_restore: true })).toThrow(
      ContractError,
    );
  });
  it('uses paged, project-scoped GET and exact POST bodies with the existing session/CSRF client', async () => {
    const entry = historyEntry({ kind: 'export' });
    const transport = vi.fn<typeof fetch>(async (url, init) => {
      if (String(url).endsWith('/session')) return json(session);
      if (String(url).endsWith('/delete')) return json(trashed(entry));
      if (String(url).endsWith('/restore')) return json({ ...entry, revision: 'c'.repeat(64) });
      if (String(url).includes('/history?'))
        return json(historyList([entry], { page: 2, total: 60 }));
      expect(init?.method).toBe('GET');
      return json(entry);
    });
    const api = historyApi(new ApiClient(transport));
    await api.history(
      { kind: 'export', project_id: entry.project_id!, page: 2 },
      new AbortController().signal,
    );
    await api.historyEntry('export', entry.id, new AbortController().signal);
    await api.deleteHistory('export', entry.id, entry.revision);
    await api.restoreHistory('export', entry.id, 'b'.repeat(64));
    const urls = transport.mock.calls.map(([url]) => String(url));
    expect(urls[1]).toBe(
      `/api/v1/history?kind=export&deleted=false&page=2&page_size=50&project_id=${entry.project_id}`,
    );
    const writes = transport.mock.calls.filter(([, init]) => init?.method === 'POST');
    expect(writes).toHaveLength(2);
    expect(writes[0]![1]).toMatchObject({
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': session.csrf_token,
      },
      body: JSON.stringify({ expected_revision: entry.revision }),
    });
    expect(writes[1]![1]?.body).toBe(JSON.stringify({ expected_revision: 'b'.repeat(64) }));
  });
  it('validates request kinds, IDs, pages and revisions before making any request', () => {
    const transport = vi.fn<typeof fetch>();
    const api = historyApi(new ApiClient(transport));
    for (const id of ['../private', '/srv/wsl/state', 'a%2fb', 'a\\b', '']) {
      expect(() => api.historyEntry('job', id, new AbortController().signal)).toThrow(
        ContractError,
      );
    }
    expect(() =>
      api.history({ kind: 'file' as HistoryKind }, new AbortController().signal),
    ).toThrow(ContractError);
    expect(() =>
      api.history({ kind: 'project', page_size: 101 }, new AbortController().signal),
    ).toThrow(ContractError);
    expect(() => api.history({ kind: 'project', page: 0 }, new AbortController().signal)).toThrow(
      ContractError,
    );
    expect(() => api.deleteHistory('project', historyProject.id, 'not-a-revision')).toThrow(
      ContractError,
    );
    expect(() =>
      api.historyEntry('export', historyProject.id, new AbortController().signal),
    ).toThrow(ContractError);
    expect(() => api.historyEntry('job', 'a'.repeat(64), new AbortController().signal)).toThrow(
      ContractError,
    );
    expect(() =>
      api.history(
        { kind: 'environment_operation', project_id: historyProject.id },
        new AbortController().signal,
      ),
    ).toThrow(ContractError);
    expect(transport).not.toHaveBeenCalled();
  });
  it('refuses responses for another resource, project, deletion filter or page', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : json(historyList([historyEntry({ kind: 'job', project_id: '4'.repeat(32) })])),
    );
    const api = historyApi(new ApiClient(transport));
    await expect(
      api.history({ kind: 'job', project_id: historyProject.id }, new AbortController().signal),
    ).rejects.toThrow(ContractError);
    transport.mockImplementation(async (url) =>
      String(url).endsWith('/session') ? json(session) : json(historyEntry()),
    );
    await expect(
      api.historyEntry('job', historyJob.id, new AbortController().signal),
    ).rejects.toThrow(ContractError);
    transport.mockImplementation(async () => json(historyList([trashed(historyEntry())])));
    await expect(
      api.history({ kind: 'project', deleted: false }, new AbortController().signal),
    ).rejects.toThrow(ContractError);
    transport.mockImplementation(async () => json(historyList([], { page: 2 })));
    await expect(
      api.history({ kind: 'project', page: 1 }, new AbortController().signal),
    ).rejects.toThrow(ContractError);
  });
  it.each(['network', 'invalid', 'wrong-resource', 'unchanged'])(
    'never replays an ambiguous %s write',
    async (failure) => {
      const entry = historyEntry();
      const transport = vi.fn<typeof fetch>(async (url) => {
        if (String(url).endsWith('/session')) return json(session);
        if (failure === 'network') throw new TypeError('offline');
        if (failure === 'invalid') return json({});
        if (failure === 'wrong-resource')
          return json(trashed(historyEntry({ id: '4'.repeat(32), project_id: '4'.repeat(32) })));
        return json(entry);
      });
      const api = historyApi(new ApiClient(transport));
      await expect(api.deleteHistory(entry.kind, entry.id, entry.revision)).rejects.toMatchObject({
        uncertain: true,
      });
      expect(transport.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    },
  );
  it('preserves JSON error envelopes without retrying HTTP write failures', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : json({ error: { code: 'history_blocked', message: '任务仍在运行' } }, 409),
    );
    const api = historyApi(new ApiClient(transport));
    await expect(api.deleteHistory('job', historyJob.id, 'a'.repeat(64))).rejects.toEqual(
      new ApiError(409, 'history_blocked', '任务仍在运行'),
    );
    expect(transport.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
  });
});
