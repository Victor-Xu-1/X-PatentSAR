import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, client } from '../src/api';
import {
  decodeEnvironmentCatalog,
  decodeEnvironmentOperation,
} from '../src/api/environmentDecoders';
import { normalizeInstallRoot } from '../src/model/environment';
import { environmentCatalog, environmentOperation } from './environment-fixtures';
import { json, session } from './fixtures';

beforeEach(() => client.resetSession());
describe('environment management exact contract', () => {
  it('decodes actual target/detected versions and does not upgrade unchecked or partial states', () => {
    expect(decodeEnvironmentCatalog(environmentCatalog)).toEqual(environmentCatalog);
    expect(decodeEnvironmentOperation(environmentOperation)).toEqual(environmentOperation);
  });
  it('defaults legacy evidence to unknown/unchecked without inferring installation from ready or a path', () => {
    const legacy = environmentCatalog.components.map((component) => {
      const value: Record<string, unknown> = { ...component };
      for (const field of ['presence', 'verification', 'checked_at', 'last_check'])
        delete value[field];
      return value;
    });
    const decoded = decodeEnvironmentCatalog({ ...environmentCatalog, components: legacy });
    for (const component of decoded.components) {
      expect(component).toMatchObject({
        presence: 'unknown',
        verification: 'unchecked',
        checked_at: null,
        last_check: null,
      });
    }
    expect(decoded.components[0]?.status).toBe('ready');
    expect(decoded.components[0]?.location).toBe(environmentCatalog.components[0]?.location);
  });
  it('retains stale evidence only in the separately supplied last check without inventing a timestamp', () => {
    const last_check = {
      status: 'ready',
      detected_version: 'previous-measured-version',
      checked_at: null,
      checks: [{ name: '旧检测', ok: true, message: '历史观察' }],
      problem: null,
    };
    const decoded = decodeEnvironmentCatalog({
      ...environmentCatalog,
      components: [
        {
          ...environmentCatalog.components[0],
          presence: 'present',
          verification: 'stale',
          checked_at: null,
          detected_version: null,
          checks: [],
          last_check,
        },
      ],
    });
    expect(decoded.components[0]).toMatchObject({
      verification: 'stale',
      checked_at: null,
      detected_version: null,
      checks: [],
      last_check,
    });
  });
  it('independently defaults omitted time/history while retaining valid supplied presence and verification', () => {
    const value: Record<string, unknown> = { ...environmentCatalog.components[0] };
    delete value.checked_at;
    delete value.last_check;
    expect(
      decodeEnvironmentCatalog({
        ...environmentCatalog,
        components: [value],
      }).components[0],
    ).toMatchObject({
      presence: 'present',
      verification: 'current',
      checked_at: null,
      last_check: null,
    });
  });
  it.each([
    { presence: 'installed' },
    { presence: null },
    { verification: 'verified' },
    { verification: null },
    { checked_at: 42 },
    { last_check: [] },
    { last_check: { status: 'installed', checks: [] } },
    { last_check: { status: 'ready', detected_version: 42, checks: [] } },
    { last_check: { status: 'ready', checked_at: false, checks: [] } },
    { last_check: { status: 'ready', checks: [{ name: '版本', ok: 'yes', message: '无效' }] } },
    { last_check: { status: 'ready', checks: [], problem: {} } },
  ])('rejects invalid supplied additive evidence: %j', (fields) => {
    expect(() =>
      decodeEnvironmentCatalog({
        ...environmentCatalog,
        components: [{ ...environmentCatalog.components[0], ...fields }],
      }),
    ).toThrow('契约');
  });
  it('rejects unapproved component IDs, duplicate inventory, invalid counters and invented progress', () => {
    expect(() =>
      decodeEnvironmentCatalog({
        ...environmentCatalog,
        components: [{ ...environmentCatalog.components[0], id: 'cuda' }],
      }),
    ).toThrow('契约');
    expect(() =>
      decodeEnvironmentCatalog({
        ...environmentCatalog,
        components: [environmentCatalog.components[0], environmentCatalog.components[0]],
      }),
    ).toThrow('契约');
    expect(() =>
      decodeEnvironmentCatalog({
        ...environmentCatalog,
        settings: { ...environmentCatalog.settings, revision: -1 },
      }),
    ).toThrow('契约');
    expect(() =>
      decodeEnvironmentOperation({ ...environmentOperation, completed_components: ['admet'] }),
    ).toThrow('契约');
  });
  it('bounds directory input to the server-approved root without accepting commands or network paths', () => {
    expect(normalizeInstallRoot(' /srv/wsl/envs/managed-next/ ', '/srv/wsl/envs')).toBe(
      '/srv/wsl/envs/managed-next',
    );
    for (const root of [
      'C:\\envs',
      '\\\\host\\share',
      'https://example.invalid',
      '/srv/wsl/envs-other',
      '//srv/wsl/envs/managed',
      '/srv/wsl/envs/../else',
      '/srv/wsl/envs/x\ncommand',
    ])
      expect(() => normalizeInstallRoot(root, '/srv/wsl/envs')).toThrow();
  });
  it('uses the existing authenticated client and only documented request fields', async () => {
    const transport = vi.fn<typeof fetch>(async (input) =>
      String(input).endsWith('/session')
        ? json(session)
        : String(input).endsWith('/settings')
          ? json(environmentCatalog.settings)
          : String(input).endsWith('/environments')
            ? json(environmentCatalog)
            : json(environmentOperation, 202),
    );
    vi.stubGlobal('fetch', transport);
    await api.environments(new AbortController().signal);
    await api.updateEnvironmentSettings('/srv/wsl/envs/managed-next', 3);
    const payload = {
      action: 'install' as const,
      component_ids: ['installer', 'base'] as const,
      request_id: environmentOperation.request_id,
      expected_revision: 3,
    };
    await api.createEnvironmentOperation({ ...payload, component_ids: [...payload.component_ids] });
    expect(JSON.parse(String(transport.mock.calls[2]![1]?.body))).toEqual({
      install_root: '/srv/wsl/envs/managed-next',
      expected_revision: 3,
    });
    expect(JSON.parse(String(transport.mock.calls[3]![1]?.body))).toEqual(payload);
    expect((transport.mock.calls[3]![1]!.headers as Record<string, string>)['X-CSRF-Token']).toBe(
      session.csrf_token,
    );
    expect(transport.mock.calls.every(([, init]) => init?.credentials === 'same-origin')).toBe(
      true,
    );
  });
  it('keeps successful HTTP writes uncertain if action/operation identity does not match', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>(async (input) =>
        String(input).endsWith('/session')
          ? json(session)
          : json({ ...environmentOperation, action: 'inspect' }, 202),
      ),
    );
    await expect(
      api.createEnvironmentOperation({
        action: 'install',
        component_ids: ['base'],
        request_id: environmentOperation.request_id,
        expected_revision: 3,
      }),
    ).rejects.toMatchObject({ code: 'invalid_write_response', uncertain: true });
    await expect(api.cancelEnvironmentOperation('another-operation')).rejects.toMatchObject({
      code: 'invalid_write_response',
      uncertain: true,
    });
  });
  it('never sends an invalid idempotency key to the transport', async () => {
    const transport = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', transport);
    expect(() =>
      api.createEnvironmentOperation({
        action: 'install',
        component_ids: ['base'],
        request_id: 'too-short',
        expected_revision: 3,
      }),
    ).toThrow('契约');
    expect(transport).not.toHaveBeenCalled();
    expect(() => api.cancelEnvironmentOperation('..')).toThrow('契约');
    expect(transport).not.toHaveBeenCalled();
  });
});
