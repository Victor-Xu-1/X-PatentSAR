import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { StudyRegionMap } from '../src/features/sar/study/StudyRegionMap';
import { setLocale } from '../src/i18n';
import { sarApi } from '../src/api/sarApi';
import { studyReport } from './sar-fixtures';
import { StudyReferencePane } from '../src/features/sar/study/StudyReferencePane';

beforeEach(() => setLocale('en'));

it('keeps every original reference grouped in one named pane without relabelling or mixing regions', async () => {
  const first = studyReport.regions[0]!;
  const report = {
    ...studyReport,
    regions: [
      first,
      {
        ...first,
        region: { ...first.region, id: 'same-reference-second-region', name: 'R2 原文' },
      },
      {
        ...first,
        reference_label: '原文 I-255',
        region: {
          ...first.region,
          id: 'other-region',
          molecule_id: 'other-reference',
          graph_sha256: 'f'.repeat(64),
          name: 'Linker 原文',
        },
      },
    ],
  };
  const original = JSON.stringify(report);
  const draw = vi.spyOn(sarApi, 'drawing');
  const { container } = render(
    <StudyRegionMap report={report} active={false} selected="other-region" onSelect={vi.fn()} />,
  );
  const pane = screen.getByRole('region', { name: 'Reference structures' });
  expect(pane).toHaveAttribute('tabindex', '-1');
  expect(container.querySelectorAll('.sar-reference-map-card')).toHaveLength(2);
  expect(within(pane).getByRole('button', { name: 'Linker 原文' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  expect(within(pane).getByRole('button', { name: 'R2 原文' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('region', { name: '参考结构' })).toBe(pane);
  expect(within(pane).getByText('参考分子区域总览 · 原文 I-255')).toBeVisible();
  expect(JSON.stringify(report)).toBe(original);
  expect(draw).not.toHaveBeenCalled();
});

it('does not create a focusable empty reference pane without a recorded region', () => {
  const { container } = render(<StudyRegionMap report={{ ...studyReport, regions: [] }} active />);
  expect(container).toBeEmptyDOMElement();
});

it('tracks actual content/viewport overflow once per frame without focus movement and disposes hidden/unmounted work', () => {
  let overflow = false;
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(300);
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(() =>
    overflow ? 600 : 300,
  );
  let notify: ResizeObserverCallback | undefined;
  const observe = vi.fn(),
    disconnect = vi.fn();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: ResizeObserverCallback) {
        notify = callback;
      }
      observe = observe;
      disconnect = disconnect;
    },
  );
  let frame: FrameRequestCallback | undefined;
  const request = vi.fn((callback: FrameRequestCallback) => {
    frame = callback;
    return 7;
  });
  const cancel = vi.fn();
  vi.stubGlobal('requestAnimationFrame', request);
  vi.stubGlobal('cancelAnimationFrame', cancel);
  const originalFocus = document.activeElement;
  const { rerender, unmount } = render(
    <StudyReferencePane active>
      <p>Original source</p>
    </StudyReferencePane>,
  );
  const pane = screen.getByRole('region', { name: 'Reference structures' });
  expect(pane).toHaveAttribute('tabindex', '-1');
  expect(observe).toHaveBeenCalledTimes(2);
  overflow = true;
  act(() => {
    notify?.([], {} as ResizeObserver);
    notify?.([], {} as ResizeObserver);
  });
  expect(request).toHaveBeenCalledTimes(1);
  act(() => frame?.(0));
  expect(pane).toHaveAttribute('tabindex', '0');
  expect(document.activeElement).toBe(originalFocus);
  act(() => notify?.([], {} as ResizeObserver));
  rerender(
    <StudyReferencePane active={false}>
      <p>Original source</p>
    </StudyReferencePane>,
  );
  expect(cancel).toHaveBeenCalledWith(7);
  expect(disconnect).toHaveBeenCalledOnce();
  expect(pane).toHaveAttribute('tabindex', '-1');
  unmount();
});

it('limits Home/End to its own viewport focus and preserves child/modifier keyboard actions', () => {
  const scroll = vi.fn();
  render(
    <StudyReferencePane active>
      <button type="button">Child action</button>
    </StudyReferencePane>,
  );
  const pane = screen.getByRole('region', { name: 'Reference structures' });
  Object.defineProperty(pane, 'scrollTo', { value: scroll });
  Object.defineProperty(pane, 'scrollHeight', { value: 600 });
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: true })),
  );
  fireEvent.keyDown(pane, { key: 'Home' });
  expect(scroll).toHaveBeenLastCalledWith({ top: 0, behavior: 'auto' });
  fireEvent.keyDown(pane, { key: 'End' });
  expect(scroll).toHaveBeenLastCalledWith({ top: 600, behavior: 'auto' });
  fireEvent.keyDown(screen.getByRole('button', { name: 'Child action' }), { key: 'Home' });
  fireEvent.keyDown(pane, { key: 'Home', ctrlKey: true });
  expect(scroll).toHaveBeenCalledTimes(2);
});
