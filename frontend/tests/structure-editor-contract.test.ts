import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Ketcher } from 'ketcher-core';
import {
  EDITOR_CHANNEL,
  readEditorLoad,
  readEditorMessage,
} from '../src/features/structure-editor/protocol';
import { subscribeDrawing } from '../src/features/structure-editor/subscribeDrawing';
import { json, session } from './fixtures';
import { client } from '../src/api';

beforeEach(() => client.resetSession());

const nativeMolfile = `
  Ketcher 3.18.0

  0  0  0     0  0            999 V3000
M  V30 BEGIN CTAB
M  V30 COUNTS 4 3 0 0 1
M  V30 BEGIN ATOM
M  V30 1 F -1 0 0 0
M  V30 2 C 0 0 0 0 CFG=1
M  V30 3 Br 1 0 0 0
M  V30 4 Cl 0 1 0 0
M  V30 END ATOM
M  V30 BEGIN BOND
M  V30 1 1 2 1 CFG=2
M  V30 2 1 2 3
M  V30 3 1 2 4
M  V30 END BOND
M  V30 BEGIN COLLECTION
M  V30 MDLV30/STEABS ATOMS=(1 2)
M  V30 END COLLECTION
M  V30 END CTAB
M  END
`;

function drawingHarness(molfile = nativeMolfile, reaction = false) {
  let change = () => {};
  const send = vi.fn();
  const getSmiles = vi.fn().mockResolvedValue('F[C@H](Br)Cl');
  const getMolfile = vi.fn().mockResolvedValue(molfile);
  const unsubscribe = vi.fn();
  const instance = {
    containsReaction: () => reaction,
    getSmiles,
    getMolfile,
    editor: {
      subscribe: (_name: string, handler: () => void) => {
        change = handler;
        return { handler };
      },
      unsubscribe,
    },
  } as unknown as Ketcher;
  return { instance, send, getSmiles, getMolfile, unsubscribe, change: () => change() };
}

function conversionTransport(smiles: string | null) {
  const transport = vi.fn((path: string, _init: RequestInit) =>
    Promise.resolve(json(path === '/api/v1/session' ? session : { smiles })),
  );
  vi.stubGlobal('fetch', transport);
  return transport;
}

describe('bounded local editor messages', () => {
  it('accepts drawing changes and load without inventing or stripping chemistry', () => {
    const load = {
      channel: EDITOR_CHANNEL,
      kind: 'load',
      smiles: '[13CH3][C@H](O)C(=O)[O-].[Na+]',
      molfile: null,
    };
    expect(readEditorLoad(load)).toEqual(load);
    expect(readEditorMessage({ channel: EDITOR_CHANNEL, kind: 'save' })).toEqual({
      channel: EDITOR_CHANNEL,
      kind: 'save',
    });
    const message = {
      channel: EDITOR_CHANNEL,
      kind: 'change',
      value: { smiles: load.smiles, molfile: null, graphKey: load.smiles, graphChanged: true },
    };
    expect(readEditorMessage(message)).toEqual(message);
  });
  it('rejects foreign, oversized, malformed and unsupported messages', () => {
    for (const message of [
      null,
      [],
      { channel: 'foreign', kind: 'ready' },
      { channel: EDITOR_CHANNEL, kind: 'execute' },
      { channel: EDITOR_CHANNEL, kind: 'error', message: 'x'.repeat(1001), recoverable: true },
      {
        channel: EDITOR_CHANNEL,
        kind: 'change',
        value: { smiles: 'x'.repeat(2049), molfile: null, graphKey: '', graphChanged: true },
      },
    ])
      expect(() => readEditorMessage(message)).toThrow();
    expect(() =>
      readEditorLoad({
        channel: EDITOR_CHANNEL,
        kind: 'load',
        smiles: '',
        molfile: 'x'.repeat(131073),
      }),
    ).toThrow();
  });
});
describe('one bounded Ketcher export stream', () => {
  it('uses the local MDL authority instead of bogus determinate native SMILES', async () => {
    vi.useFakeTimers();
    const transport = conversionTransport('FC(Cl)Br');
    const { instance, send, change, getSmiles, getMolfile } = drawingHarness();
    const close = subscribeDrawing(instance, 'F[C@H](Br)Cl', send);
    change();
    await vi.advanceTimersByTimeAsync(100);
    expect(send).toHaveBeenLastCalledWith({
      kind: 'change',
      value: {
        smiles: 'FC(Cl)Br',
        molfile: nativeMolfile,
        graphKey: 'FC(Cl)Br',
        graphChanged: true,
      },
    });
    expect(getSmiles).not.toHaveBeenCalled();
    expect(getMolfile).toHaveBeenCalledExactlyOnceWith('v3000');
    expect(transport).toHaveBeenLastCalledWith(
      '/api/v1/chemistry/structure',
      expect.objectContaining({
        method: 'POST',
        credentials: 'same-origin',
        body: JSON.stringify({ molfile: nativeMolfile }),
      }),
    );
    expect(
      new Headers(transport.mock.calls.at(-1)![1].headers).get('X-CSRF-Token') ===
        session.csrf_token,
    ).toBe(true);
    close();
  });
  it('times out without a polling loop and ignores late results after closing', async () => {
    vi.useFakeTimers();
    let release: ((value: string) => void) | undefined;
    const never = new Promise<string>((resolve) => {
      release = resolve;
    });
    const { instance, send, change, getMolfile, getSmiles } = drawingHarness();
    getMolfile.mockReturnValue(never);
    const transport = conversionTransport('FC(Cl)Br');
    const close = subscribeDrawing(instance, '', send);
    change();
    await vi.advanceTimersByTimeAsync(15100);
    expect(send).toHaveBeenLastCalledWith({
      kind: 'error',
      recoverable: false,
      message: '绘图导出超时，请重新加载编辑器。',
    });
    expect(getSmiles).not.toHaveBeenCalled();
    expect(transport).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(30000);
    expect(getMolfile).toHaveBeenCalledOnce();
    close();
    const count = send.mock.calls.length;
    release?.(nativeMolfile);
    await vi.advanceTimersByTimeAsync(1);
    expect(send).toHaveBeenCalledTimes(count);
    expect(transport).not.toHaveBeenCalled();
  });
  it('serializes latest-change MDL exports and drops stale conversion results', async () => {
    vi.useFakeTimers();
    let release: ((value: Response) => void) | undefined;
    const first = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const transport = vi
      .fn()
      .mockResolvedValueOnce(json(session))
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce(json({ smiles: 'CCO' }));
    vi.stubGlobal('fetch', transport);
    const { instance, send, change, getMolfile, getSmiles } = drawingHarness();
    getMolfile.mockResolvedValueOnce(nativeMolfile).mockResolvedValueOnce('latest MDL');
    const close = subscribeDrawing(instance, '', send);
    change();
    await vi.advanceTimersByTimeAsync(100);
    change();
    change();
    await vi.advanceTimersByTimeAsync(100);
    expect(getMolfile).toHaveBeenCalledOnce();
    expect(transport).toHaveBeenCalledTimes(2);
    release?.(json({ smiles: 'FC(Cl)Br' }));
    await vi.advanceTimersByTimeAsync(1);
    expect(send.mock.calls.some(([message]) => message.kind === 'change')).toBe(false);
    await vi.advanceTimersByTimeAsync(100);
    expect(send).toHaveBeenLastCalledWith({
      kind: 'change',
      value: { smiles: 'CCO', molfile: 'latest MDL', graphKey: 'CCO', graphChanged: true },
    });
    expect(getMolfile).toHaveBeenCalledTimes(2);
    expect(getSmiles).not.toHaveBeenCalled();
    expect(transport).toHaveBeenCalledTimes(3);
    close();
  });
  it('debounces changes, retains coordinate-only values and unsubscribes on close', async () => {
    vi.useFakeTimers();
    const { instance, send, change, getMolfile, getSmiles, unsubscribe } =
      drawingHarness('molfile');
    conversionTransport('CCO');
    const close = subscribeDrawing(instance, 'CCO', send);
    change();
    change();
    change();
    await vi.advanceTimersByTimeAsync(100);
    expect(getMolfile).toHaveBeenCalledOnce();
    expect(getSmiles).not.toHaveBeenCalled();
    expect(send).toHaveBeenLastCalledWith({
      kind: 'change',
      value: { smiles: 'CCO', molfile: 'molfile', graphKey: 'CCO', graphChanged: false },
    });
    close();
    expect(unsubscribe).toHaveBeenCalledOnce();
  });
  it('clears only a backend-confirmed empty drawing', async () => {
    vi.useFakeTimers();
    conversionTransport(null);
    const { instance, send, change } = drawingHarness('empty MDL with zero atoms');
    const close = subscribeDrawing(instance, 'CCO', send);
    change();
    await vi.advanceTimersByTimeAsync(100);
    expect(send).toHaveBeenLastCalledWith({
      kind: 'change',
      value: { smiles: '', molfile: null, graphKey: '', graphChanged: true },
    });
    close();
  });
  it('fails unsupported stereo closed without fallback, rewriting or a change message', async () => {
    vi.useFakeTimers();
    const transport = vi
      .fn()
      .mockResolvedValueOnce(json(session))
      .mockResolvedValueOnce(
        json(
          {
            error: { code: 'structure_conversion_invalid', message: 'OR/AND stereo unsupported' },
          },
          422,
        ),
      );
    vi.stubGlobal('fetch', transport);
    const { instance, send, change, getSmiles } = drawingHarness();
    const close = subscribeDrawing(instance, 'CCO', send);
    change();
    await vi.advanceTimersByTimeAsync(100);
    expect(send).toHaveBeenLastCalledWith({
      kind: 'error',
      recoverable: true,
      message: 'OR/AND stereo unsupported',
    });
    expect(send.mock.calls.some(([message]) => message.kind === 'change')).toBe(false);
    expect(getSmiles).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(30000);
    expect(transport).toHaveBeenCalledTimes(2);
    close();
  });
  it.each(['session', 'conversion'])(
    'settles on close during %s and forbids late POST/change',
    async (stage) => {
      vi.useFakeTimers();
      let release: ((value: Response) => void) | undefined;
      const pending = new Promise<Response>((resolve) => {
        release = resolve;
      });
      const transport = vi.fn();
      if (stage === 'conversion') transport.mockResolvedValueOnce(json(session));
      transport.mockReturnValueOnce(pending);
      vi.stubGlobal('fetch', transport);
      const { instance, send, change, unsubscribe } = drawingHarness();
      const close = subscribeDrawing(instance, '', send);
      change();
      await vi.advanceTimersByTimeAsync(100);
      const signal = transport.mock.calls.at(-1)![1].signal as AbortSignal;
      expect(signal.aborted).toBe(false);
      close();
      // The shared bootstrap may finish its read-only GET; an active POST is aborted.
      expect(signal.aborted).toBe(stage === 'conversion');
      expect(unsubscribe).toHaveBeenCalledOnce();
      const messages = send.mock.calls.length,
        requests = transport.mock.calls.length;
      release?.(json(stage === 'session' ? session : { smiles: 'CCO' }));
      await vi.advanceTimersByTimeAsync(20000);
      expect(send).toHaveBeenCalledTimes(messages);
      expect(transport).toHaveBeenCalledTimes(requests);
      expect(vi.getTimerCount()).toBe(0);
    },
  );
  it('fails reaction export rather than producing a molecule-shaped success', async () => {
    vi.useFakeTimers();
    const { instance, send, change, getMolfile } = drawingHarness(nativeMolfile, true);
    const transport = conversionTransport('CCO');
    const close = subscribeDrawing(instance, '', send);
    change();
    await vi.advanceTimersByTimeAsync(100);
    expect(send).toHaveBeenLastCalledWith({
      kind: 'error',
      recoverable: false,
      message: '请绘制分子结构，不使用反应箭头。',
    });
    expect(getMolfile).not.toHaveBeenCalled();
    expect(transport).not.toHaveBeenCalled();
    close();
  });
});
