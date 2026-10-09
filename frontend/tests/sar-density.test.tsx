import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { setLocale } from '../src/i18n';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { ContextPicker } from '../src/features/sar/study/ContextPicker';
import { StudyResults } from '../src/features/sar/study/StudyResults';
import { studyContext, sarDataset, studyJob, studyReport } from './sar-fixtures';

beforeEach(() => setLocale('en'));
describe('concise source-owned activity selection', () => {
  it('shows the actual selectable count, avoids duplicate repeat counts, and preserves raw conditions and selection on language change', async () => {
    const onSelect = vi.fn();
    const contexts = [0, 1, 2, 3].map((index) => ({
      ...studyContext,
      id: String(index).repeat(64),
      name: '原文 EC50-' + index,
      molecule_count: 3,
      observation_count: index ? 3 : 5,
    }));
    const { rerender } = render(
      <ContextPicker contexts={contexts} selected={[]} onSelect={onSelect} />,
    );
    const group = screen.getByRole('group', { name: 'Choose activity measurements · 0/4' });
    expect(within(group).getAllByText('3 molecules')).toHaveLength(3);
    expect(within(group).getByText('3 molecules · 5 observations')).toBeVisible();
    expect(screen.queryByText('3 molecules · 3 observations')).not.toBeInTheDocument();
    const choice = screen.getByRole('checkbox', { name: /原文 EC50-1/ });
    await userEvent.click(choice);
    expect(onSelect).toHaveBeenCalledExactlyOnceWith(contexts[1]!.id, true);
    rerender(
      <ContextPicker contexts={contexts} selected={[contexts[1]!.id]} onSelect={onSelect} />,
    );
    await act(() => setLocale('zh-CN'));
    expect(screen.getByRole('group', { name: '选择活性指标 · 1/4' })).toBeVisible();
    expect(screen.getByRole('checkbox', { name: /原文 EC50-1/ })).toBe(choice);
    expect(choice).toBeChecked();
    expect(screen.getAllByText('raw assay · raw target')).toHaveLength(4);
  });
  it('retains the eight-context cap and allows deselection without guessing or dropping IDs', async () => {
    const contexts = Array.from({ length: 9 }, (_, index) => ({
      ...studyContext,
      id: String(index).repeat(64),
      name: 'Original metric ' + index,
    }));
    const onSelect = vi.fn();
    render(
      <ContextPicker
        contexts={contexts}
        selected={contexts.slice(0, 8).map((item) => item.id)}
        onSelect={onSelect}
      />,
    );
    expect(screen.getByRole('group', { name: 'Choose activity measurements · 8/8' })).toBeVisible();
    expect(screen.getByRole('checkbox', { name: /Original metric 8/ })).toBeDisabled();
    const selected = screen.getByRole('checkbox', { name: /Original metric 7/ });
    expect(selected).toBeEnabled();
    await userEvent.click(selected);
    expect(onSelect).toHaveBeenCalledExactlyOnceWith(contexts[7]!.id, false);
  });
});
describe('compact but truthful study heading', () => {
  it('keeps real completion, historical scope and research status in one header without rewriting the user title', async () => {
    vi.spyOn(sarApi, 'job').mockResolvedValue(studyJob);
    vi.spyOn(sarStudyApi, 'overview').mockResolvedValue({ job: studyJob, report: studyReport });
    const { container } = render(
      <StudyResults
        dataset={{ ...sarDataset, stale: true }}
        jobId={studyJob.id}
        active
        disabled={false}
        scope="current"
        onJob={vi.fn()}
      />,
    );
    await screen.findByRole('heading', { name: studyReport.title });
    const header = container.querySelector('.sar-study-header');
    expect(header).not.toBeNull();
    const state = within(header! as HTMLElement);
    expect(state.getByText('Complete')).toBeVisible();
    expect(state.getByText('Historical study')).toBeVisible();
    expect(state.getByText('Research preview')).toBeVisible();
    await userEvent.click(state.getByRole('button', { name: 'Details' }));
    expect(await screen.findByRole('dialog', { name: 'Details' })).toBeVisible();
  });
});
