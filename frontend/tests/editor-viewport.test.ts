import { describe, expect, it, vi } from 'vitest';
import type { Ketcher } from 'ketcher-core';
import {
  fitEditorViewport,
  observeEditorViewport,
} from '../src/features/structure-editor/editorViewport';

function fixture(width = 500, height = 400) {
  const molecule = {
    atoms: { size: 2 },
    getCoordBoundingBox: () => ({ min: { x: -8, y: -3 }, max: { x: 10, y: 9 } }),
  };
  const box = { minX: 0, minY: 0, width, height };
  const render = {
    options: { microModeScale: 40, macroModeScale: 40, zoom: 1 },
    clientArea: { getBoundingClientRect: () => ({ width, height }) },
    setViewBox: vi.fn((change) => change(box)),
  };
  const instance = {
    editor: {
      render,
      struct: vi.fn(() => molecule),
      zoom: vi.fn(),
      event: { zoomChanged: { dispatch: vi.fn() } },
    },
    setMolecule: vi.fn(),
    layout: vi.fn(),
  };
  return { instance: instance as unknown as Ketcher, native: instance, molecule, box };
}

describe('chemistry-preserving viewport fit', () => {
  it('publishes the fitted scale through the native zoom-feedback event, without a graph action', () => {
    const { instance, native } = fixture();
    fitEditorViewport(instance);
    expect(native.editor.event.zoomChanged.dispatch).toHaveBeenCalledOnce();
    expect(native.layout).not.toHaveBeenCalled();
    expect(native.setMolecule).not.toHaveBeenCalled();
  });
  it('coalesces resize notifications and disconnects without a polling loop or graph action', () => {
    const { instance, native } = fixture();
    const frames = new Map<number, () => void>();
    let next = 0,
      resized = () => {};
    const disconnect = vi.fn(),
      observe = vi.fn();
    vi.stubGlobal('requestAnimationFrame', (action: () => void) => {
      frames.set(++next, action);
      return next;
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(action: () => void) {
          resized = action;
        }
        observe = observe;
        disconnect = disconnect;
      },
    );
    const stop = observeEditorViewport(instance);
    resized();
    resized();
    expect(frames.size).toBe(1);
    frames.get(next)!();
    frames.delete(next);
    expect(native.editor.zoom).toHaveBeenCalledOnce();
    expect(observe).toHaveBeenCalledExactlyOnceWith(native.editor.render.clientArea);
    resized();
    stop();
    expect(frames.size).toBe(0);
    expect(disconnect).toHaveBeenCalledOnce();
    resized();
    frames.get(next)?.();
    expect(frames.size).toBe(0);
    expect(native.editor.zoom).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });
  it('fits both dimensions from the actual canvas and centers the viewport without modifying the molecule', () => {
    const { instance, native, molecule } = fixture();
    const original = JSON.stringify(molecule);
    expect(fitEditorViewport(instance)).toBe(true);
    expect(native.editor.zoom).toHaveBeenCalledWith(
      Math.min(1, (500 - 64) / 720, (400 - 64) / 480),
    );
    const view = native.editor.render.setViewBox.mock.results[0]!.value;
    expect(view.minX + view.width / 2).toBe(40);
    expect(view.minY + view.height / 2).toBe(120);
    expect(JSON.stringify(molecule)).toBe(original);
    expect(native.setMolecule).not.toHaveBeenCalled();
    expect(native.layout).not.toHaveBeenCalled();
  });
  it('waits for usable dimensions without requesting layout or inventing a scale', () => {
    const { instance, native } = fixture(0, 0);
    expect(fitEditorViewport(instance)).toBe(false);
    expect(native.editor.zoom).not.toHaveBeenCalled();
    expect(native.editor.render.setViewBox).not.toHaveBeenCalled();
  });
  it('respects the native minimum scale on a very small viewport and keeps empty drawings unchanged', () => {
    const { instance, native, molecule } = fixture(70, 70);
    expect(fitEditorViewport(instance)).toBe(true);
    expect(native.editor.zoom).toHaveBeenCalledWith(0.1);
    native.editor.zoom.mockClear();
    molecule.atoms.size = 0;
    expect(fitEditorViewport(instance)).toBe(false);
    expect(native.editor.zoom).not.toHaveBeenCalled();
  });
});
