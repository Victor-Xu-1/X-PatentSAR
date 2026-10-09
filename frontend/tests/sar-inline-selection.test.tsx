import { act, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { RegionLegend } from '../src/features/sar/study/RegionMap';
import { StudyViewTabs } from '../src/features/sar/study/StudyViewTabs';
import { namedRegion } from './sar-fixtures';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it('coalesces resize work and releases observer/animation work without changing focus or selection', () => {
  let width = 200,
    resized = () => {};
  const frames = new Map<number, FrameRequestCallback>();
  let next = 0;
  const disconnect = vi.fn(),
    observe = vi.fn(),
    onSelect = vi.fn();
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frames.set(++next, callback);
    return next;
  });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: () => void) {
        resized = callback;
      }
      observe = observe;
      disconnect = disconnect;
    },
  );
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    const strip = this.closest('ul');
    return (
      this.tagName === 'UL'
        ? { left: 0, right: width, width }
        : {
            left: 240 - (strip?.scrollLeft ?? 0),
            right: 360 - (strip?.scrollLeft ?? 0),
            width: 120,
          }
    ) as DOMRect;
  });
  const { unmount } = render(
    <RegionLegend regions={[namedRegion]} selected={namedRegion.id} onSelect={onSelect} />,
  );
  const strip = screen.getByRole('button', { name: namedRegion.name! }).closest('ul')!;
  expect(strip.scrollLeft).toBe(160);
  expect(observe).toHaveBeenCalledExactlyOnceWith(strip);
  width = 140;
  act(() => {
    resized();
    resized();
  });
  expect(frames.size).toBe(1);
  act(() => {
    frames.get(next)!(0);
    frames.delete(next);
  });
  expect(strip.scrollLeft).toBe(220);
  expect(onSelect).not.toHaveBeenCalled();
  act(() => resized());
  unmount();
  expect(frames.size).toBe(0);
  expect(disconnect).toHaveBeenCalledOnce();
  resized();
  expect(frames.size).toBe(0);
  expect(window.scrollY).toBe(0);
});

it('keeps programmatically selected result controls visible without moving page focus', () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    const strip = this.closest('nav');
    return (
      this.tagName === 'NAV'
        ? { left: 0, right: 200, width: 200 }
        : {
            left: 240 - (strip?.scrollLeft ?? 0),
            right: 360 - (strip?.scrollLeft ?? 0),
            width: 120,
          }
    ) as DOMRect;
  });
  const { rerender } = render(
    <StudyViewTabs
      labels={['研究概览', '研究活性表']}
      selected={0}
      panelId="owned"
      onSelect={vi.fn()}
    />,
  );
  const strip = screen.getByRole('navigation');
  expect(strip.scrollLeft).toBe(160);
  rerender(
    <StudyViewTabs
      labels={['研究概览', '研究活性表']}
      selected={1}
      panelId="owned"
      onSelect={vi.fn()}
    />,
  );
  expect(strip.scrollLeft).toBe(160);
  expect(strip.querySelector('[aria-current]')).toHaveAttribute('aria-controls', 'owned-1');
  expect(document.activeElement).toBe(document.body);
});

it('does no work for a hidden or nonselected strip', () => {
  const onSelect = vi.fn();
  render(
    <RegionLegend regions={[namedRegion]} selected="not-this-reference" onSelect={onSelect} />,
  );
  const strip = screen.getByRole('button', { name: namedRegion.name! }).closest('ul')!;
  expect(strip.scrollLeft).toBe(0);
  expect(onSelect).not.toHaveBeenCalled();
});
