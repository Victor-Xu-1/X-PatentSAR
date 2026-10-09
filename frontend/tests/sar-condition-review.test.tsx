import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { setLocale } from '../src/i18n';
import { StudySetup } from '../src/features/sar/study/StudySetup';
import { SourceAcceptance } from '../src/features/sar/study/SourceAcceptance';
import { declarationFromDraft, emptyCondition } from '../src/features/sar/study/conditionDraft';
import { decodeConditionDeclaration } from '../src/api/sarConditionDecoders';
import { sarDataset, studyContext, studyJob, studyProfile } from './sar-fixtures';

const dataset = {
  ...sarDataset,
  source_page_count: 20,
  source_acceptance: { state: 'historical' as const, errors: ['Original source limitation'] },
};
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue(studyProfile);
  vi.spyOn(sarStudyApi, 'start').mockResolvedValue(studyJob);
});
describe('source-anchored condition review', () => {
  it('does not infer conditions and refuses absent notes, invalid pages or unknown values', () => {
    const draft = {
      ...emptyCondition(),
      enabled: true,
      fields: { duration: '2 h' },
      pages: '18',
      note: 'Original method checked',
    };
    expect(declarationFromDraft(dataset, studyContext, draft)?.source_pages).toEqual([18]);
    expect(declarationFromDraft(dataset, studyContext, { ...draft, note: '' })).toBeNull();
    expect(declarationFromDraft(dataset, studyContext, { ...draft, pages: '21' })).toBeNull();
    expect(
      declarationFromDraft(dataset, studyContext, { ...draft, fields: { duration: 'unknown' } }),
    ).toBeNull();
    expect(
      declarationFromDraft({ ...dataset, source_page_count: null }, studyContext, draft),
    ).toBeNull();
    expect(declarationFromDraft(dataset, studyContext, emptyCondition())).toBeNull();
  });
  it('retains input through language changes and sends an explicit declaration, never a source edit', async () => {
    render(<StudySetup dataset={dataset} active disabled={false} scope="review" onJob={vi.fn()} />);
    await userEvent.click(await screen.findByRole('checkbox', { name: /IC50 原文.*raw assay/ }));
    await userEvent.selectOptions(screen.getByLabelText('Activity direction'), 'lower');
    await userEvent.click(screen.getByText('Document missing assay conditions'));
    await userEvent.click(
      screen.getByRole('checkbox', {
        name: 'I checked the source and document conditions for this study',
      }),
    );
    expect(screen.getByRole('button', { name: 'Run full study' })).toBeDisabled();
    expect(screen.queryByLabelText('Target')).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Cell line'), 'Cells C 原文');
    const duration = screen.getByLabelText('Treatment duration');
    await userEvent.type(duration, '2 h');
    await userEvent.type(screen.getByLabelText('Source pages (comma-separated)'), '18,19');
    await userEvent.type(screen.getByLabelText('Source-review note'), 'Checked methods 原文');
    await act(() => setLocale('zh-CN'));
    expect(screen.getByLabelText('处理时长')).toBe(duration);
    expect(duration).toHaveValue('2 h');
    await userEvent.click(screen.getByRole('button', { name: '运行完整研究' }));
    await waitFor(() => expect(sarStudyApi.start).toHaveBeenCalledOnce());
    expect(vi.mocked(sarStudyApi.start).mock.calls[0]?.[1]).toMatchObject({
      confirm_context: false,
      context_declarations: [
        {
          context_id: studyContext.id,
          fields: { cell_line: 'Cells C 原文', duration: '2 h' },
          source_document_sha256: dataset.source_document_sha256,
          source_pages: [18, 19],
          note: 'Checked methods 原文',
        },
      ],
    });
    expect(studyContext.context.cell_line).toBeNull();
  });
  it('keeps historical QA and absent provenance visibly different from accepted source extraction', () => {
    const { rerender } = render(<SourceAcceptance source={dataset.source_acceptance} />);
    expect(screen.getByText('Source extraction: historical')).toBeInTheDocument();
    rerender(<SourceAcceptance source={null} />);
    expect(screen.getByText('Source QA not recorded')).toBeInTheDocument();
    rerender(<SourceAcceptance source={{ state: 'accepted', errors: [] }} />);
    expect(screen.getByText('Source extraction: QA passed')).toBeInTheDocument();
  });
  it('rejects foreign condition field roles and impossible source references in response decoding', () => {
    const claim = {
      context_id: studyContext.id,
      fields: { duration: '2 h' },
      source_document_sha256: 'a'.repeat(64),
      source_pages: [18],
      note: 'Checked source',
    };
    expect(decodeConditionDeclaration(claim)).toEqual(claim);
    for (const changed of [
      { fields: { unit: 'uM' } },
      { source_pages: [0] },
      { source_pages: [18, 18] },
      { note: '' },
    ])
      expect(() => decodeConditionDeclaration({ ...claim, ...changed })).toThrow();
  });
});
