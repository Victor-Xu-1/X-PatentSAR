import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { setLocale } from '../src/i18n';
import { decodeStudyPreview } from '../src/api/sarPreviewDecoder';
import { PreviewProperties } from '../src/features/sar/study/PreviewProperties';
import { sarPair, studyJob, studyReport, studyRow } from './sar-fixtures';

const data = decodeStudyPreview({
  job: studyJob,
  region: studyReport.regions[0]!.region,
  reference: studyRow,
  candidate: { ...studyRow, molecule_id: 'different-source', label: '原文 I-255' },
  pair: {
    ...sarPair,
    reference_id: studyRow.molecule_id,
    molecule_id: 'different-source',
    region_id: studyReport.regions[0]!.region.id,
    match_status: 'matched',
  },
  measurements: [],
  property_differences: {},
});
let notify: ResizeObserverCallback | undefined;
let frame: FrameRequestCallback | undefined;
let width = 310;
beforeEach(() => {
  setLocale('en');
  width = 310;
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => width);
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(560);
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: ResizeObserverCallback) {
        notify = callback;
      }
      observe = vi.fn();
      disconnect = vi.fn();
    },
  );
  vi.stubGlobal(
    'requestAnimationFrame',
    vi.fn((callback: FrameRequestCallback) => {
      frame = callback;
      return 7;
    }),
  );
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: true })),
  );
});

it('offers bounded user-operated scrolling only for real overflow, without translating or changing source data', async () => {
  const original = JSON.stringify(data);
  const { container } = render(<PreviewProperties data={data} />);
  const port = container.querySelector('.sar-property-comparison')! as HTMLElement;
  let offset = 0;
  Object.defineProperty(port, 'scrollLeft', { get: () => offset });
  const scroll = vi.fn(({ left }: ScrollToOptions) => {
    offset = Math.min(250, Math.max(0, offset + (left ?? 0)));
    fireEvent.scroll(port);
  });
  Object.defineProperty(port, 'scrollBy', { value: scroll });
  expect(screen.getByRole('button', { name: 'Scroll properties left' })).toBeDisabled();
  await userEvent.click(screen.getByRole('button', { name: 'Scroll properties right' }));
  act(() => frame?.(0));
  expect(scroll).toHaveBeenLastCalledWith({ left: 248, behavior: 'auto' });
  expect(screen.getByRole('button', { name: 'Scroll properties left' })).toBeEnabled();
  await userEvent.click(screen.getByRole('button', { name: 'Scroll properties right' }));
  act(() => frame?.(0));
  expect(screen.getByRole('button', { name: 'Scroll properties right' })).toBeDisabled();
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('button', { name: '向左滚动性质' })).toBeEnabled();
  expect(screen.getByRole('table', { name: '性质' }).querySelector('tbody')).toHaveTextContent(
    '原文 I-255',
  );
  expect(JSON.stringify(data)).toBe(original);
});

it('removes redundant controls and keyboard stops when resized to fit, with no focus movement', () => {
  const { container, unmount } = render(
    <>
      <button type="button">Other control</button>
      <PreviewProperties data={data} />
    </>,
  );
  const port = container.querySelector('.sar-property-comparison')!;
  const other = screen.getByRole('button', { name: 'Other control' });
  other.focus();
  expect(screen.getByRole('button', { name: 'Scroll properties right' })).toBeVisible();
  expect(port).toHaveAttribute('tabindex', '0');
  width = 700;
  act(() => {
    notify?.([], {} as ResizeObserver);
    frame?.(0);
  });
  expect(screen.queryByRole('button', { name: 'Scroll properties right' })).not.toBeInTheDocument();
  expect(port).toHaveAttribute('tabindex', '-1');
  expect(other).toHaveFocus();
  unmount();
});
