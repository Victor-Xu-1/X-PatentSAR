import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { EnvironmentProgress } from '../src/features/environment/EnvironmentProgress';
import { environmentOperation } from './environment-fixtures';

const properties = () => ({
  selected: environmentOperation,
  selectionId: environmentOperation.id,
  loading: false,
  busy: false,
  readError: false,
  onCancel: vi.fn().mockResolvedValue(null),
  onReload: vi.fn(),
});
it('pins cancellation to the originally confirmed operation and refuses a stale target after navigation', async () => {
  const props = properties();
  const view = render(<EnvironmentProgress {...props} />);
  await userEvent.click(screen.getByRole('button', { name: '取消此环境操作' }));
  view.rerender(
    <EnvironmentProgress
      {...props}
      selected={{ ...environmentOperation, id: 'another-owned-operation' }}
      selectionId="another-owned-operation"
    />,
  );
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(props.onCancel).not.toHaveBeenCalled();
});
it('distinguishes completed installation from actual applied configuration and never invents progress', () => {
  const props = properties();
  const operation = {
    ...environmentOperation,
    status: 'complete' as const,
    completed_components: environmentOperation.component_ids,
    applied: false,
  };
  const view = render(<EnvironmentProgress {...props} selected={operation} />);
  expect(screen.getByText(/配置尚未应用/)).toBeVisible();
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '取消此环境操作' })).not.toBeInTheDocument();
  view.rerender(<EnvironmentProgress {...props} selected={{ ...operation, applied: true }} />);
  expect(screen.queryByLabelText('环境配置进度')).not.toBeInTheDocument();
});
it('does not reopen a previous cancel confirmation after completion and a new operation', async () => {
  const props = properties();
  const view = render(<EnvironmentProgress {...props} />);
  await userEvent.click(screen.getByRole('button', { name: '取消此环境操作' }));
  view.rerender(
    <EnvironmentProgress
      {...props}
      selected={{ ...environmentOperation, status: 'complete', applied: true }}
    />,
  );
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  const next = { ...environmentOperation, id: 'next-owned-operation' };
  view.rerender(<EnvironmentProgress {...props} selected={next} selectionId={next.id} />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '取消此环境操作' }));
  await userEvent.click(screen.getByRole('button', { name: '确认取消此环境操作' }));
  expect(props.onCancel).toHaveBeenCalledExactlyOnceWith(next.id);
});
