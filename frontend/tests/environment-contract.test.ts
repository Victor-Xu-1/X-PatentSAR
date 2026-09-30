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
