import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../src/api/errors';
import { UncertainSARWrite } from '../src/api/sarMutation';
import { SARFailure } from '../src/features/sar/SARFailure';
import { MutationNotice } from '../src/features/sar/MutationNotice';
import { useSARMutation } from '../src/features/sar/useSARMutation';
import { setLocale, UiError } from '../src/i18n';

beforeEach(() => setLocale('en'));

it('keeps the read alert short and wire details collapsed until requested', async () => {
  const error = new ApiError(
    503,
    'sar_controlled_read_failure',
    'Original identifier 原文/I-255 is unavailable.',
  );
  const original = JSON.stringify({ code: error.code, source: error.source, values: error.values });
  const reload = vi.fn();
  const view = render(<SARFailure error={error} onRetry={reload} />);
  expect(screen.getByRole('alert')).toHaveTextContent('Unable to load SAR data.');
  expect(screen.getByRole('alert')).not.toHaveTextContent(error.code);
  const details = view.container.querySelector('details')!;
  expect(details).not.toHaveAttribute('open');
  expect(within(details).getByText(error.source)).not.toBeVisible();
  await userEvent.click(screen.getByText('Error details', { exact: true }));
  expect(details).toHaveAttribute('open');
  expect(within(details).getByText(error.source)).toBeVisible();
  expect(within(details).getByText(error.code)).toBeVisible();
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('alert')).toHaveTextContent('无法读取 SAR 数据。');
  expect(details).toHaveAttribute('open');
  expect(within(details).getByText(error.source)).toBeVisible();
  expect(reload).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
  expect(reload).toHaveBeenCalledOnce();
  expect(JSON.stringify({ code: error.code, source: error.source, values: error.values })).toBe(
    original,
  );
});

it('keeps a definite operation failure distinct from a read failure', () => {
  const view = render(
    <SARFailure
      error={new ApiError(422, 'sar_invalid_region', 'Source region 原文 is disconnected.')}
    />,
  );
  expect(screen.getByRole('alert')).toHaveTextContent('The SAR operation failed.');
  expect(screen.queryByRole('button', { name: 'Reload' })).not.toBeInTheDocument();
  expect(view.container.querySelector('details')).not.toHaveAttribute('open');
});

it('never turns an unconfirmed write into a definite failure and keeps its identity secondary', async () => {
  const id = 'a'.repeat(32);
  const error = new ApiError(
    503,
    'sar_unconfirmed',
    'SAR 写入响应无法确认。请核对服务器状态，勿重复提交。',
    true,
  );
  const view = render(<SARFailure error={error} requestId={id} />);
  expect(screen.getByRole('alert')).toHaveTextContent('could not be confirmed');
  expect(screen.getByRole('alert')).not.toHaveTextContent('operation failed');
  const details = view.container.querySelector('details')!;
  expect(within(details).getByText('Request identity: ' + id)).not.toBeVisible();
  await userEvent.click(screen.getByText('Error details', { exact: true }));
  expect(within(details).getByText('Request identity: ' + id)).toBeVisible();
  expect(within(details).getByText('sar_unconfirmed')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Reload' })).not.toBeInTheDocument();
});

it('preserves mutation locking and does not replay a captured write when inspecting its details', async () => {
  const id = 'b'.repeat(32);
  const failure = new UncertainSARWrite(
    new ApiError(
      503,
      'sar_uncertain_import',
      'SAR 写入响应无法确认。请核对服务器状态，勿重复提交。',
      true,
    ),
    id,
  );
  const action = vi.fn().mockRejectedValue(failure);
  function Driver() {
    const mutation = useSARMutation({ scope: 'controlled-error-scope' });
    return (
      <>
        <button type="button" onClick={() => void mutation.run(action, vi.fn(), id)}>
          Controlled write
        </button>
        <output aria-label="Mutation locked">{String(mutation.locked)}</output>
        <MutationNotice mutation={mutation} />
      </>
    );
  }
  const view = render(<Driver />);
  await userEvent.click(screen.getByRole('button', { name: 'Controlled write' }));
  await screen.findByRole('alert');
  expect(screen.getByLabelText('Mutation locked')).toHaveTextContent('true');
  const details = view.container.querySelector('details')!;
  expect(within(details).getByText('Request identity: ' + id)).not.toBeVisible();
  await userEvent.click(screen.getByText('Error details', { exact: true }));
  await act(() => setLocale('zh-CN'));
  expect(within(details).getByText('请求身份：' + id)).toBeVisible();
  expect(screen.getByLabelText('Mutation locked')).toHaveTextContent('true');
  expect(action).toHaveBeenCalledOnce();
});

it('renders wire messages as text, never as markup', async () => {
  const message = '<img src=x onerror=alert(1)> · Original 原文';
  const view = render(<SARFailure error={new ApiError(422, 'sar_invalid_input', message)} />);
  await userEvent.click(screen.getByText('Error details', { exact: true }));
  expect(screen.getByText(message)).toBeVisible();
  expect(view.container.querySelector('img')).toBeNull();
});

it('retains the original human-facing non-SAR error path', () => {
  const error = new UiError('RDKit 结构图加载失败。');
  const view = render(<SARFailure error={error} />);
  expect(screen.getByRole('alert')).toHaveTextContent('The RDKit drawing could not be loaded.');
  expect(view.container.querySelector('details')).toBeNull();
});
