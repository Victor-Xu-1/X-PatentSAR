import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render } from '@testing-library/react';
import type { ReactElement } from 'react';
import type { Ketcher } from 'ketcher-core';
import { EDITOR_CHANNEL } from '../src/features/structure-editor/protocol';
import { json, session } from './fixtures';
import { client } from '../src/api';

const frame = vi.hoisted(() => ({
  element: null as ReactElement | null,
  instance: null as Ketcher | null,
}));
vi.mock('react-dom/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-dom/client')>();
  return {
    ...actual,
    createRoot: (container: Element | DocumentFragment) => {
      if (container instanceof Element && container.id === 'ketcher-root')
        return {
          render: (element: ReactElement) => {
            frame.element = element;
          },
        };
      return actual.createRoot(container);
    },
  };
});
vi.mock('ketcher-standalone/dist/binaryWasmNoRender', () => ({
  StandaloneStructServiceProvider: class {},
}));
vi.mock('ketcher-react', async () => {
  const { useEffect } = await import('react');
  return {
    Editor: ({ onInit }: { onInit: (instance: Ketcher) => void }) => {
      useEffect(() => {
        onInit(frame.instance!);
      }, [onInit]);
      return <div>Controlled Ketcher contract</div>;
    },
  };
});

let change = () => {};
beforeAll(async () => {
  const entry = document.createElement('div');
  entry.id = 'ketcher-root';
  document.body.append(entry);
  await import('../src/features/structure-editor/frameEntry');
  entry.remove();
});
beforeEach(() => {
  client.resetSession();
  vi.useFakeTimers();
  change = () => {};
  frame.instance = {
    setMolecule: vi.fn().mockResolvedValue(undefined),
    containsReaction: () => false,
    getMolfile: vi.fn().mockResolvedValue('unchanged loaded MDL'),
    getSmiles: vi.fn().mockResolvedValue('bogus native SMILES'),
    editor: {
      subscribe: vi.fn((_name: string, handler: () => void) => {
        change = handler;
      }),
      unsubscribe: vi.fn(),
    },
  } as unknown as Ketcher;
});

async function load(smiles = 'OCC') {
  await act(async () => {
    window.dispatchEvent(
      new MessageEvent('message', {
        source: window.parent,
        origin: window.location.origin,
        data: { channel: EDITOR_CHANNEL, kind: 'load', smiles, molfile: null },
      }),
    );
    await vi.advanceTimersByTimeAsync(1);
  });
}

describe('initial editor graph and failure boundary', () => {
  it('loads and compares the same backend canonical key without consulting getSmiles', async () => {
    const transport = vi.fn((path: string) =>
      Promise.resolve(json(path === '/api/v1/session' ? session : { smiles: 'CCO' })),
    );
    vi.stubGlobal('fetch', transport);
    const send = vi.spyOn(window.parent, 'postMessage').mockImplementation(() => {});
    const view = render(frame.element!);
    await load('OCC');
    expect(send).toHaveBeenLastCalledWith(
      { channel: EDITOR_CHANNEL, kind: 'loaded' },
      window.location.origin,
    );
    await act(async () => {
      change();
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(send).toHaveBeenLastCalledWith(
      {
        channel: EDITOR_CHANNEL,
        kind: 'change',
        value: {
          smiles: 'CCO',
          molfile: 'unchanged loaded MDL',
          graphKey: 'CCO',
          graphChanged: false,
        },
      },
      window.location.origin,
    );
    expect(frame.instance!.getSmiles).not.toHaveBeenCalled();
    expect(frame.instance!.getMolfile).toHaveBeenCalledTimes(2);
    view.unmount();
  });
  it('does not send loaded or enable save after unsupported initial chemistry', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(json(session))
        .mockResolvedValueOnce(
          json(
            {
              error: { code: 'structure_conversion_invalid', message: 'Unsupported stereo' },
            },
            422,
          ),
        ),
    );
    const send = vi.spyOn(window.parent, 'postMessage').mockImplementation(() => {});
    render(frame.element!);
    await load();
    expect(send).toHaveBeenLastCalledWith(
      { channel: EDITOR_CHANNEL, kind: 'error', recoverable: true, message: 'Unsupported stereo' },
      window.location.origin,
    );
    expect(send.mock.calls.some(([message]) => message.kind === 'loaded')).toBe(false);
    expect(frame.instance!.editor.subscribe).toHaveBeenCalledOnce();
  });
  it('aborts the initial backend conversion when the frame is disposed', async () => {
    let release: ((response: Response) => void) | undefined;
    const transport = vi
      .fn()
      .mockResolvedValueOnce(json(session))
      .mockReturnValueOnce(
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
      );
    vi.stubGlobal('fetch', transport);
    const send = vi.spyOn(window.parent, 'postMessage').mockImplementation(() => {});
    const view = render(frame.element!);
    await load();
    const signal = transport.mock.calls[1]![1].signal as AbortSignal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    const messages = send.mock.calls.length;
    release?.(json({ smiles: 'CCO' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(send).toHaveBeenCalledTimes(messages);
    expect(vi.getTimerCount()).toBe(0);
  });
});
