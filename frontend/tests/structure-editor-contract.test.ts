import { describe, expect, it, vi } from 'vitest';
import type { Ketcher } from 'ketcher-core';
import {
  EDITOR_CHANNEL,
  readEditorLoad,
  readEditorMessage,
} from '../src/features/structure-editor/protocol';
import { subscribeDrawing } from '../src/features/structure-editor/subscribeDrawing';

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
  it('times out without a polling loop and ignores late results after closing', async () => {
    vi.useFakeTimers();
    let change: (() => void) | undefined, release: ((value: string) => void) | undefined;
    const never = new Promise<string>((resolve) => {
      release = resolve;
    });
    const send = vi.fn(),
      getSmiles = vi.fn().mockReturnValue(never);
    const instance = {
      containsReaction: () => false,
      getSmiles,
      getMolfile: vi.fn(),
      editor: {
        subscribe: (_name: string, handler: () => void) => {
          change = handler;
        },
        unsubscribe: vi.fn(),
      },
    } as unknown as Ketcher;
    const close = subscribeDrawing(instance, '', send);
    change?.();
    await vi.advanceTimersByTimeAsync(15100);
    expect(send).toHaveBeenLastCalledWith({
      kind: 'error',
      recoverable: false,
      message: '绘图导出超时，请重新加载编辑器。',
    });
    expect(instance.getMolfile).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(30000);
    expect(getSmiles).toHaveBeenCalledOnce();
    close();
    const count = send.mock.calls.length;
    release?.('CCO');
    await vi.advanceTimersByTimeAsync(1);
    expect(send).toHaveBeenCalledTimes(count);
    vi.useRealTimers();
  });
  it('serializes format conversions because the SDK correlates them by input, not output format', async () => {
    vi.useFakeTimers();
    let change: (() => void) | undefined, release: ((value: string) => void) | undefined;
    const smiles = new Promise<string>((resolve) => {
      release = resolve;
    });
    const instance = {
      containsReaction: () => false,
      getSmiles: () => smiles,
      getMolfile: vi.fn().mockResolvedValue('MDL V3000'),
      editor: {
        subscribe: (_name: string, handler: () => void) => {
          change = handler;
        },
        unsubscribe: vi.fn(),
      },
    } as unknown as Ketcher;
    const send = vi.fn(),
      close = subscribeDrawing(instance, '', send);
    change?.();
    await vi.advanceTimersByTimeAsync(100);
    expect(instance.getMolfile).not.toHaveBeenCalled();
    release?.('CCO');
    await vi.advanceTimersByTimeAsync(1);
    expect(send).toHaveBeenLastCalledWith({
      kind: 'change',
      value: { smiles: 'CCO', molfile: 'MDL V3000', graphKey: 'CCO', graphChanged: true },
    });
    close();
    vi.useRealTimers();
  });
  it('debounces changes, retains coordinate-only values and unsubscribes on close', async () => {
    vi.useFakeTimers();
    let change: (() => void) | undefined;
    const unsubscribe = vi.fn(),
      send = vi.fn();
    const instance = {
      containsReaction: () => false,
      getSmiles: vi.fn().mockResolvedValue('CCO'),
      getMolfile: vi.fn().mockResolvedValue('molfile'),
      editor: {
        subscribe: (_name: string, handler: () => void) => {
          change = handler;
          return { handler };
        },
        unsubscribe,
      },
    } as unknown as Ketcher;
    const close = subscribeDrawing(instance, 'CCO', send);
    change?.();
    change?.();
    change?.();
    await vi.advanceTimersByTimeAsync(100);
    expect(instance.getSmiles).toHaveBeenCalledOnce();
    expect(send).toHaveBeenLastCalledWith({
      kind: 'change',
      value: { smiles: 'CCO', molfile: 'molfile', graphKey: 'CCO', graphChanged: false },
    });
    close();
    expect(unsubscribe).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });
  it('fails reaction export rather than producing a molecule-shaped success', async () => {
    vi.useFakeTimers();
    let change: (() => void) | undefined;
    const send = vi.fn();
    const instance = {
      containsReaction: () => true,
      editor: {
        subscribe: (_name: string, handler: () => void) => {
          change = handler;
        },
        unsubscribe: vi.fn(),
      },
    } as unknown as Ketcher;
    const close = subscribeDrawing(instance, '', send);
    change?.();
    await vi.advanceTimersByTimeAsync(100);
    expect(send).toHaveBeenLastCalledWith({
      kind: 'error',
      recoverable: false,
      message: '请绘制分子结构，不使用反应箭头。',
    });
    close();
    vi.useRealTimers();
  });
});
