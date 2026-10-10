import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { setLocale } from '../src/i18n';
import { StudyImage } from '../src/features/sar/study/StudyImage';
import { sarDrawing } from './sar-fixtures';

const props = {
  jobId: 'owned-study',
  kind: 'molecule' as const,
  identifier: 'owned-molecule',
  label: 'I-007B 原文',
  active: true,
  inspectable: true,
};
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarStudyApi, 'drawing').mockResolvedValue({ id: props.identifier, svg: sarDrawing.svg });
});

it('opens only a loaded, validated current drawing and magnifies the same passive source without extra reads', async () => {
  render(<StudyImage {...props} />);
  const original = await screen.findByRole('img', { name: props.label });
  expect(
    screen.queryByRole('button', { name: 'Enlarge structure ' + props.label }),
  ).not.toBeInTheDocument();
  fireEvent.load(original);
  const opener = screen.getByRole('button', { name: 'Enlarge structure ' + props.label });
  await userEvent.click(opener);
  const dialog = screen.getByRole('dialog', { name: 'Molecular preview · ' + props.label });
  const image = within(dialog).getByRole('img', { name: props.label });
  expect(image.getAttribute('src')).toBe(original.getAttribute('src'));
  const zoom = within(dialog).getByLabelText('Magnification relative to fit');
  const pane = within(dialog).getByRole('region', { name: 'Molecular canvas' });
  expect(zoom).toHaveTextContent('100%');
  expect(pane).toHaveAttribute('tabindex', '-1');
  expect(within(dialog).getByRole('button', { name: 'Zoom out structure' })).toBeDisabled();
  for (let i = 0; i < 12; i++)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Zoom in structure' }));
  expect(zoom).toHaveTextContent('400%');
  expect(pane).toHaveAttribute('tabindex', '0');
  expect(within(dialog).getByRole('button', { name: 'Zoom in structure' })).toBeDisabled();
  expect(image.parentElement).toHaveStyle({ width: '400%', height: '400%' });
  await userEvent.click(within(dialog).getByRole('button', { name: 'Fit' }));
  expect(zoom).toHaveTextContent('100%');
  expect(pane).toHaveAttribute('tabindex', '-1');
  const url = image.getAttribute('src');
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('dialog', { name: '结构预览 · ' + props.label })).toBe(dialog);
  expect(image).toHaveAttribute('src', url);
  expect(sarStudyApi.drawing).toHaveBeenCalledOnce();
  fireEvent.error(image);
  expect(within(dialog).getByRole('alert')).toHaveTextContent('RDKit 结构图加载失败');
  fireEvent(dialog, new Event('cancel', { cancelable: true }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(opener).toHaveFocus();
});

it('closes on deactivation or changed drawing identity, never reopening a stale preview after revalidation', async () => {
  const { rerender } = render(<StudyImage {...props} />);
  fireEvent.load(await screen.findByRole('img', { name: props.label }));
  await userEvent.click(screen.getByRole('button', { name: 'Enlarge structure ' + props.label }));
  rerender(<StudyImage {...props} active={false} />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: 'Enlarge structure ' + props.label }),
  ).not.toBeInTheDocument();
  rerender(<StudyImage {...props} />);
  await waitFor(() => expect(sarStudyApi.drawing).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await userEvent.click(
    await screen.findByRole('button', { name: 'Enlarge structure ' + props.label }),
  );
  rerender(<StudyImage {...props} atomRegionId="different-exact-region" />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await waitFor(() => expect(sarStudyApi.drawing).toHaveBeenCalledTimes(3));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('withholds magnification for unsafe markup, request failures and failed images', async () => {
  vi.mocked(sarStudyApi.drawing).mockResolvedValueOnce({
    id: props.identifier,
    svg: '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
  });
  const { rerender } = render(<StudyImage {...props} />);
  await screen.findByRole('alert');
  expect(screen.queryByRole('button', { name: /Enlarge structure/ })).not.toBeInTheDocument();
  vi.mocked(sarStudyApi.drawing).mockRejectedValueOnce(new Error('controlled read failure'));
  rerender(<StudyImage {...props} identifier="failed-read" />);
  await screen.findByText('controlled read failure');
  expect(screen.queryByRole('button', { name: /Enlarge structure/ })).not.toBeInTheDocument();
  rerender(<StudyImage {...props} identifier="failed-image" />);
  const image = await screen.findByRole('img', { name: props.label });
  fireEvent.error(image);
  await screen.findByRole('alert');
  expect(screen.queryByRole('button', { name: /Enlarge structure/ })).not.toBeInTheDocument();
});

it('cannot magnify before the current read completes and does not authorize cached data during revalidation', async () => {
  let resolve!: (value: { id: string; svg: string }) => void;
  vi.mocked(sarStudyApi.drawing).mockReturnValueOnce(
    new Promise((value) => {
      resolve = value;
    }),
  );
  render(<StudyImage {...props} />);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Enlarge structure/ })).not.toBeInTheDocument();
  await act(async () => resolve({ id: props.identifier, svg: sarDrawing.svg }));
  const image = screen.getByRole('img', { name: props.label });
  expect(screen.queryByRole('button', { name: /Enlarge structure/ })).not.toBeInTheDocument();
  fireEvent.load(image);
  expect(screen.getByRole('button', { name: 'Enlarge structure ' + props.label })).toBeEnabled();
});

it('leaves normal table and fragment thumbnails unchanged unless inspection is explicitly enabled', async () => {
  render(<StudyImage {...props} inspectable={false} />);
  const image = await screen.findByRole('img', { name: props.label });
  fireEvent.load(image);
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
