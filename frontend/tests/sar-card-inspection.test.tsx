import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { setLocale } from '../src/i18n';
import { StudyLeads } from '../src/features/sar/study/StudyLeads';
import { StudyScaffolds } from '../src/features/sar/study/StudyScaffolds';
import { StudyFragmentCard } from '../src/features/sar/study/StudyFragmentCard';
import {
  coreRegion,
  namedRegion,
  sarDrawing,
  sarMolecule,
  studyFragment,
  studyJob,
  studyProfile,
  studyReport,
} from './sar-fixtures';

beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue(studyProfile);
  vi.spyOn(sarStudyApi, 'drawing').mockImplementation(async (_job, _kind, identifier) => ({
    id: identifier,
    svg: sarDrawing.svg,
  }));
});

const cases = [
  {
    kind: 'lead',
    label: sarMolecule.label,
    translated: sarMolecule.label,
    drawingKind: 'molecule',
    identifier: sarMolecule.id,
    region: '',
    element: <StudyLeads report={studyReport} jobId={studyJob.id} active onSource={vi.fn()} />,
  },
  {
    kind: 'core',
    label: coreRegion.name!,
    translated: coreRegion.name!,
    drawingKind: 'scaffold',
    identifier: studyReport.scaffolds[0]!.id,
    region: '',
    element: <StudyScaffolds report={studyReport} jobId={studyJob.id} active onRows={vi.fn()} />,
  },
  {
    kind: 'fragment',
    label: 'Fragment 1',
    translated: '片段 1',
    drawingKind: 'fragment',
    identifier: studyFragment.id,
    region: namedRegion.id,
    element: (
      <StudyFragmentCard
        fragment={studyFragment}
        index={1}
        regionId={namedRegion.id}
        referenceId={namedRegion.molecule_id}
        jobId={studyJob.id}
        active
        onRows={vi.fn()}
        unit="molecules"
        report={studyReport}
        onPreview={vi.fn()}
      />
    ),
  },
] as const;

it.each(cases)(
  '$kind card opens the same validated drawing with a concise label and no extra read',
  async (sample) => {
    const originalReport = JSON.stringify(studyReport);
    render(sample.element);
    const image = await screen.findByRole('img', { name: sample.label });
    const opener = screen.getByRole('button', { name: 'Enlarge structure ' + sample.label });
    expect(opener).toContainElement(image);
    expect(opener).toBeDisabled();
    fireEvent.load(image);
    await userEvent.click(opener);
    const dialog = screen.getByRole('dialog', { name: 'Molecular preview · ' + sample.label });
    const expanded = within(dialog).getByRole('img', { name: sample.label });
    expect(expanded.getAttribute('src')).toBe(image.getAttribute('src'));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Zoom in structure' }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Fit' }));
    await act(() => setLocale('zh-CN'));
    expect(screen.getByRole('dialog', { name: '结构预览 · ' + sample.translated })).toBe(dialog);
    expect(within(dialog).getByRole('img', { name: sample.translated })).toHaveAttribute(
      'src',
      image.getAttribute('src'),
    );
    expect(sarStudyApi.drawing).toHaveBeenCalledOnce();
    expect(vi.mocked(sarStudyApi.drawing).mock.calls[0]?.slice(0, 3)).toEqual([
      studyJob.id,
      sample.drawingKind,
      sample.identifier,
    ]);
    expect(vi.mocked(sarStudyApi.drawing).mock.calls[0]?.[4] ?? '').toBe(sample.region);
    fireEvent(dialog, new Event('cancel', { cancelable: true }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(JSON.stringify(studyReport)).toBe(originalReport);
  },
);
