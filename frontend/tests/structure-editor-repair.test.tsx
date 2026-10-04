import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import StructureEditor from '../src/features/results/StructureEditor';
import { EDITOR_CHANNEL } from '../src/features/structure-editor/protocol';

describe('unsupported structure can be redrawn, never saved before valid conversion', () => {
  it('keeps repairable canvas active but blocks save until a validated change', () => {
    const ready = vi.fn();
    render(
      <StructureEditor
        smiles="CCO"
        molfile={null}
        disabled={false}
        onChange={vi.fn()}
        onReady={ready}
        onSave={vi.fn()}
      />,
    );
    const frame = screen.getByTitle('Ketcher 结构绘制与预览') as HTMLIFrameElement;
    const send = (payload: object) =>
      act(() => {
        window.dispatchEvent(
          new MessageEvent('message', {
            origin: window.location.origin,
            source: frame.contentWindow,
            data: { channel: EDITOR_CHANNEL, ...payload },
          }),
        );
      });
    send({ kind: 'error', message: 'unsupported stereo', recoverable: true });
    expect(ready).toHaveBeenLastCalledWith(false);
    expect(screen.getByLabelText('结构式绘制区域')).toHaveAttribute('aria-disabled', 'false');
    send({
      kind: 'change',
      value: {
        smiles: 'CCO',
        molfile: 'controlled MDL payload',
        graphKey: 'CCO',
        graphChanged: true,
      },
    });
    expect(ready).toHaveBeenLastCalledWith(true);
    expect(screen.queryByText('unsupported stereo')).toBeNull();
  });
});
