import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { PageCanvas } from '../src/features/pdf/PageCanvas';
import { PdfPane } from '../src/features/pdf/PdfPane';
import { compound, page, project } from './fixtures';

const key = 'a'.repeat(64);
const selection = { compoundId: compound.id, key };
const focused = {
  ...page,
  activity_focus: {
    compound_id: compound.id,
    activity_key: key,
    status: 'located' as const,
    boxes: [[120, 240, 160, 260] as [number, number, number, number]],
    message: null,
  },
};
const props = {
  zoom: 1,
  annotations: false,
  selectedId: null,
  onSelect: vi.fn(),
  activityFocus: selection,
};
const pane = {
  project,
  page: 4,
  tab: 'original' as const,
  selectedId: null,
  activityFocus: selection,
  onPage: vi.fn(),
  onTab: vi.fn(),
  onSelect: vi.fn(),
  onAttach: vi.fn(),
};
describe('genuine activity-coordinate PDF overlays', () => {
  it('waits for the actual PNG, then outlines only the returned cell and scrolls it into view', () => {
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView');
    const { container } = render(<PageCanvas {...props} page={focused} />);
    expect(container.querySelector('[data-activity-focus]')).toBeNull();
    fireEvent.load(screen.getByRole('img'));
    const mark = container.querySelector('[data-activity-focus]')!;
    expect(mark).toHaveAttribute('data-activity-focus', key);
    expect(mark).toHaveStyle({ left: '60%', top: '80%', width: '20%' });
    expect(container.querySelector('[data-annotation]')).toBeNull();
    expect(scroll).toHaveBeenCalledWith(
      expect.objectContaining({ block: 'center', inline: 'nearest' }),
    );
  });
  it('keeps rendered-page geometry accurate after zoom and ignores stale same-page selection', () => {
    const { container, rerender } = render(<PageCanvas {...props} page={focused} />);
    fireEvent.load(screen.getByRole('img'));
    expect(container.querySelector('[data-activity-focus]')).not.toBeNull();
    const next = { ...selection, key: 'b'.repeat(64) };
    rerender(<PageCanvas {...props} activityFocus={next} page={focused} />);
    expect(container.querySelector('[data-activity-focus]')).toBeNull();
    rerender(<PageCanvas {...props} page={focused} zoom={1.5} />);
    expect(container.querySelector('[data-activity-focus]')).toBeNull();
    fireEvent.load(screen.getByRole('img'));
    expect(container.querySelector('[data-activity-focus]')).toHaveStyle({
      left: '60%',
      top: '80%',
    });
    expect(container.querySelector('.page-canvas')).toHaveStyle({ width: '150%' });
    fireEvent.error(screen.getByRole('img', { name: '原始专利 PDF 第 4 页' }));
    expect(container.querySelector('[data-activity-focus]')).toBeNull();
    expect(screen.getByText('页面图像加载失败')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '重新加载页面图像' }));
    expect(container.querySelector('[data-activity-focus]')).toBeNull();
  });
  it('shows page-only provenance honestly, without borrowing a structure annotation', async () => {
    vi.spyOn(api, 'page').mockResolvedValue({
      ...focused,
      activity_focus: { ...focused.activity_focus, status: 'page_only', boxes: [] },
    });
    render(<PdfPane {...pane} />);
    expect(await screen.findByText('该活性仅有来源页，缺少可核验的原文坐标')).toBeVisible();
    fireEvent.load(screen.getByRole('img'));
    expect(document.querySelector('[data-activity-focus]')).toBeNull();
    expect(document.querySelector('[data-annotation]')).toBeNull();
  });
  it('explains legacy page-only navigation without fabricating a coordinate request', async () => {
    const load = vi.spyOn(api, 'page').mockResolvedValue(page);
    render(<PdfPane {...pane} activityFocus={undefined} activityPageOnly />);
    expect(await screen.findByText('该活性仅有来源页，缺少可核验的原文坐标')).toBeVisible();
    expect(load).toHaveBeenCalledExactlyOnceWith(project.id, 4, expect.any(AbortSignal));
    fireEvent.load(screen.getByRole('img'));
    expect(document.querySelector('[data-activity-focus]')).toBeNull();
  });
  it('uses rendered dimensions even when the original page is rotated and retains annotation interaction', () => {
    const rotated = {
      ...focused,
      width: 300,
      height: 200,
      activity_focus: {
        ...focused.activity_focus,
        boxes: [[30, 40, 60, 80] as [number, number, number, number]],
      },
    };
    const select = vi.fn();
    const { container } = render(
      <PageCanvas
        {...props}
        page={rotated}
        annotations
        selectedId={compound.id}
        onSelect={select}
      />,
    );
    fireEvent.load(screen.getByRole('img'));
    expect(container.querySelector('[data-activity-focus]')).toHaveStyle({
      left: '10%',
      top: '20%',
      width: '10%',
      height: '20%',
    });
    fireEvent.click(screen.getByRole('button', { name: /定位化合物/ }));
    expect(select).toHaveBeenCalledWith(compound.id);
  });
  it('changes the existing resource key on a same-page metric switch and clears previous marks while loading', async () => {
    let resolve!: (value: typeof focused) => void;
    const load = vi
      .spyOn(api, 'page')
      .mockResolvedValueOnce(focused)
      .mockImplementationOnce(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      );
    const { rerender } = render(<PdfPane {...pane} />);
    fireEvent.load(await screen.findByRole('img'));
    expect(document.querySelector('[data-activity-focus]')).not.toBeNull();
    const next = { ...selection, key: 'b'.repeat(64) };
    rerender(<PdfPane {...pane} activityFocus={next} />);
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    expect(load).toHaveBeenLastCalledWith(project.id, 4, expect.any(AbortSignal), next);
    expect(document.querySelector('[data-activity-focus]')).toBeNull();
    resolve({ ...focused, activity_focus: { ...focused.activity_focus, activity_key: next.key } });
    fireEvent.load(await screen.findByRole('img'));
    await waitFor(() =>
      expect(document.querySelector('[data-activity-focus]')).toHaveAttribute(
        'data-activity-focus',
        next.key,
      ),
    );
  });
});
