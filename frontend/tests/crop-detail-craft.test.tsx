import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { CropDialog } from '../src/features/results/CropDialog';
import { setLocale } from '../src/i18n';
import { compound } from './fixtures';

beforeEach(() => setLocale('en'));
const row = {
  ...compound,
  id: 'source row / 7B',
  display_id: 'Example 7B',
  smiles: 'C[C@H](O)[13CH3]',
  source: { ...compound.source, page: 79 },
  redraw_image_url: '/api/v1/projects/control/redraw',
};

it('starts with original/redraw previews, closed raw chemistry, and a direct safe original-source action', async () => {
  const close = vi.fn();
  render(<CropDialog compound={row} projectId="project / source" onClose={close} />);
  const smiles = screen.getByLabelText('Current SMILES');
  expect(smiles).toHaveValue(row.smiles);
  expect(smiles).not.toBeVisible();
  const disclosure = screen.getByText('Current SMILES', { selector: 'summary' });
  await userEvent.click(disclosure);
  expect(smiles).toBeVisible();
  await act(() => setLocale('zh-CN'));
  expect(screen.getByLabelText('当前 SMILES')).toBe(smiles);
  expect(smiles).toHaveValue(row.smiles);
  const source = screen.getByRole('link', { name: '查看原文' });
  expect(source).toHaveAttribute(
    'href',
    '#/projects/project%20%2F%20source?page=79&tab=original&compound=source%20row%20%2F%207B',
  );
  await userEvent.click(source);
  expect(close).toHaveBeenCalledOnce();
});

it.each([null, 0, -1, 1.5])('never invents a source-page action for %s', (page) => {
  render(
    <CropDialog
      compound={{ ...row, source: { ...row.source, page } }}
      projectId="source"
      onClose={vi.fn()}
    />,
  );
  expect(screen.queryByRole('link', { name: 'View original' })).not.toBeInTheDocument();
  expect(screen.getByRole('img', { name: 'Original structure crop for Example 7B' })).toBeVisible();
});

it('keeps invalid-chemistry and missing-source reasons visible while raw technical content stays secondary', () => {
  render(
    <CropDialog
      compound={{
        ...row,
        structure_image_url: null,
        flags: ['structure_not_generated'],
        recognition: {
          status: 'invalid',
          quality_flag: null,
          model_fingerprint: null,
          token_confidence: null,
        },
      }}
      projectId="source"
      onClose={vi.fn()}
    />,
  );
  expect(screen.getByText('Structure crop not generated yet')).toBeVisible();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Current SMILES')).not.toBeVisible();
});

it('uses one source preview rather than a full empty redraw panel when no redraw is usable', async () => {
  const reason = '已保留结构原图；尚未证实原文编号，不能猜测或按活性集合分配编号。';
  const { container } = render(
    <CropDialog
      compound={{
        ...row,
        smiles: null,
        redraw_image_url: null,
        confidence: { ...row.confidence, reason },
      }}
      projectId="source"
      onClose={vi.fn()}
    />,
  );
  expect(container.querySelector('.crop-comparison')).toHaveClass('crop-comparison--source-only');
  expect(container.querySelectorAll('.crop-comparison figure')).toHaveLength(1);
  expect(container.querySelector('.prediction-evidence')).toBeNull();
  expect(screen.getByText('SMILES not provided; redraw unavailable')).toBeVisible();
  await userEvent.click(
    screen.getByText('Original extraction evidence / validation', { selector: 'summary' }),
  );
  expect(
    screen.getByText(/Source image retained; original identifier unconfirmed[.]/),
  ).toBeVisible();
  await act(() => setLocale('zh-CN'));
  expect(screen.getByText(/原图已保留，原文编号待核验。/)).toBeVisible();
});

it('keeps real prediction failures visible even when the molecular preview is unavailable', async () => {
  render(
    <CropDialog
      compound={{
        ...row,
        smiles: null,
        redraw_image_url: null,
        admet: {
          status: 'failed',
          properties: [],
          warnings: [],
          review_only: true,
          source_fingerprint: null,
          smiles_sha256: null,
          engine: null,
          generated_at: null,
          job_id: null,
          error: { code: 'controlled_failure', message: 'Controlled prediction failure' },
        },
      }}
      projectId="source"
      onClose={vi.fn()}
    />,
  );
  await userEvent.click(screen.getByText(/Six properties/, { selector: 'summary' }));
  expect(screen.getByText('Controlled prediction failure')).toBeVisible();
});
